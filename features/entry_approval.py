# features/entry_approval.py

import logging
import time
import tempfile
import threading
import os
import json

from praw.models import Redditor
from praw.models.reddit.modmail import ModmailConversation
from bs4 import BeautifulSoup  # Import BeautifulSoup for HTML parsing

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

class EntryApprovalFeature:
    def __init__(self, reddit, subreddit, signature, openai_api_key):
        self.reddit = reddit
        self.subreddit = subreddit
        self.signature = signature
        self.target_subreddits = ['superstonk', 'gme', 'deepfuckingvalue', 'gme_meltdown']  # Extend as needed

        # Initialize LangChain components
        self.llm = ChatOpenAI(model="gpt-4o",openai_api_key=openai_api_key)
        self.prompt_template = PromptTemplate(
            input_variables=["user_comments"],
            template=(
                "Given the following user comments/posts:\n{user_comments}\n\n"
                "Assess whether the user should be admitted to the subreddit based on the criteria:\n\n"
                
                "1. Engagement and Contribution: Does the user actively participate in discussions, respond to others’ comments, and contribute thoughtful, substantive content?\n"
                "2. Inclusivity and Respect: Does the user demonstrate respectful behavior towards others, without using discriminatory, exclusionary, or hostile language (swearing is okay)?\n"
                "3. Relevance to GME and Stocks: Are the user's comments and posts primarily focused on GME or other relevant stock discussions?\n"
                "4. Constructive Dialogue: Does the user foster constructive, respectful discussions, even in political or controversial contexts?\n"
                "5. Active Learning and Engagement: Does the user engage with their posts, respond to feedback, ask questions, and show a willingness to learn?\n"
                "6. No Self-Promotion or Spam: Does the user avoid self-promotion, calls to action, or spam behavior?\n\n"

                "Start your response solely with a verdict of 'Admit', 'Deny', or 'Uncertain' followed directly by a brief justification.  In your justification, quote specific language snippets they've used if it contributed to the decision."
            )
        )
        self.llm_chain = self.prompt_template | self.llm

        # Initialize processed conversations set
        self.processed_conversations_file = 'processed_conversations.json'
        self.processed_conversations_lock = threading.Lock()
        self.processed_conversations = self.load_processed_conversations()

    def load_processed_conversations(self):
        if os.path.exists(self.processed_conversations_file):
            try:
                with open(self.processed_conversations_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'conversations' in data:
                        return set(data['conversations'])
                    else:
                        logging.warning("Processed conversations file is not in expected format.")
                        return set()
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Error reading processed conversations file: {e}")
                return set()
        else:
            return set()


    def save_processed_conversations(self):
        try:
            with self.processed_conversations_lock:
                data = {'conversations': list(self.processed_conversations)}
                with tempfile.NamedTemporaryFile('w', delete=False, dir='.', suffix='.tmp') as tf:
                    json.dump(data, tf)
                    tempname = tf.name
                os.replace(tempname, self.processed_conversations_file)
        except IOError as e:
            logging.error(f"Error saving processed conversations: {e}")


    def mark_conversation_processed(self, conversation_id):
        self.processed_conversations.add(conversation_id)
        self.save_processed_conversations()

    def run(self, DEBUG=False):
        logging.info("Starting EntryApprovalFeature...")
        if (DEBUG):
            #recommendation, justification = self.analyze_user(self.reddit.redditor("welp007"), "")
            #print(recommendation)
            #print(justification)
            self.process_join_requests()
            return
        while True:
            try:
                self.process_join_requests()
            except Exception as e:
                logging.error(f"Error in EntryApprovalFeature: {e}")
            time.sleep(300)  # Check every 300 seconds

    def process_join_requests(self):
        # Fetch modmail conversations in 'join_requests' state
        modmail_conversations = self.subreddit.modmail.conversations(state='join_requests')
        for conversation in modmail_conversations:
            conversation_id = conversation.id  # The conversation's base36 ID

            # Skip if we have already processed this conversation
            if conversation_id in self.processed_conversations:
                continue

            author = conversation.user
            if author is None:
                self.mark_conversation_processed(conversation_id)
                continue
            username = author.name

            # Check if the user has already been approved
            if self.is_user_approved(author):
                self.mark_conversation_processed(conversation_id)
                continue  # Skip processing

            # Check if the bot has already replied in the conversation
            if self.has_prior_conversation(author, conversation):
                self.mark_conversation_processed(conversation_id)
                continue  # Skip processing

            # Get the initial modmail message
            initial_message_html = conversation.messages[0].body

            # Clean the HTML using BeautifulSoup
            initial_message = self.clean_html(initial_message_html)
            initial_message_truncated = self.truncate_text(initial_message, max_length=300)
            logging.info(f"Initial message from u/{username}: {initial_message}")

            # Analyze the user's activity and get a recommendation
            recommendation, justification, author_hidden = self.analyze_user(author, initial_message)

            # Send a recommendation to the modmail thread, visible only to mods (author_hidden=True)
            recommendation_message = (
                f"Recommendation for u/{username}: **{recommendation}**\n\n"
                f"Justification:\n{justification}\n\n"
                f"A human mod review will take the final action.\n\n"
                f"*Note:* This AI-assisted recommendation feature does not represent the final verdict. It is used to provide a non-bias assessment of comment/post history based on the subreddit's goals."
            )

            conversation.reply(recommendation_message, author_hidden=author_hidden)
            logging.info(f"Sent recommendation {recommendation} for u/{username} to the mods.")

            # After processing, mark the conversation as processed
            self.mark_conversation_processed(conversation_id)


    def analyze_user(self, user: Redditor, initial_message: str):
        top_comments = []
        cont_comments = []
        top_posts = []
        cont_posts = []
        max_length = 300  # Set the maximum length for comments/posts

        # Fetch user's top comments from target subreddits
        for comment in user.comments.top(limit=1000):
            if comment.subreddit.display_name.lower() in self.target_subreddits:
                truncated_comment = self.truncate_text(comment.body, max_length=max_length)
                top_comments.append(truncated_comment)
            if len(top_comments) >= 10:  # Limit to top 10 comments
                break

        # Fetch user's controversial comments from target subreddits
        for comment in user.comments.controversial(limit=1000):
            if comment.subreddit.display_name.lower() in self.target_subreddits:
                truncated_comment = self.truncate_text(comment.body, max_length=max_length)
                if truncated_comment not in top_comments:
                    cont_comments.append(truncated_comment)
            if len(cont_comments) >= 10:  # Limit to total of 10 comments
                break

        # Fetch user's top posts from target subreddits
        for post in user.submissions.top(limit=100):
            if post.subreddit.display_name.lower() in self.target_subreddits:
                truncated_post = self.truncate_text(f"Title: {post.title}, Body: {post.selftext}", max_length=max_length)
                top_posts.append(truncated_post)
            if len(top_posts) >= 5:  # Limit to top 5 posts
                break

        # Fetch user's controversial posts from target subreddits
        for post in user.submissions.controversial(limit=100):
            if post.subreddit.display_name.lower() in self.target_subreddits:
                truncated_post = self.truncate_text(f"Title: {post.title}, Body: {post.selftext}", max_length=max_length)
                if truncated_post not in top_posts:
                    cont_posts.append(truncated_post)
            if len(cont_posts) >= 5:  # Limit to total of 10 posts
                break

        if not top_comments and not top_posts:
            return 'Uncertain', 'No relevant activity found.', True

        # Combine the initial message with the comments and posts
        user_content = (
            f"Initial Modmail Message:\n{initial_message}\n\n"
            "Comments:\n" + "\n\n".join(top_comments) + "\n\n".join(cont_comments) + 
            "\n\nPosts:\n" + "\n\n".join(top_posts) + "\n\n".join(cont_posts)
        )

        # Run through LLM
        response = self.llm_chain.invoke({"user_comments": user_content})
        response_content = response.content

        # Parse the LLM response
        lines = response_content.strip().split('\n')
        verdict = lines[0].split(':')[-1].strip()
        justification = '\n'.join(lines[1:]).strip()
        return verdict, justification, False

    def is_user_approved(self, user: Redditor):
        try:
            # Check if the user is an approved contributor in the subreddit
            for contributor in self.subreddit.contributor(limit=None):
                if contributor.name == user.name:
                    return True
            return False
        except Exception as e:
            logging.error(f"Error checking if user is approved: {e}")
            return False

    def has_prior_conversation(self, user: Redditor, conversation: ModmailConversation):
        try:
            # Get the bot's username (assuming it's the same as the authenticated Reddit user)
            bot_username = self.reddit.user.me().name

            # Check if the conversation is already in a processed state
            if conversation.state in ['archived', 'mod_actioned', 'appeal', 'joined']:
                return True  # User has already been processed (approved or rejected)
            
            # Check if the bot has already commented on the conversation
            for message in conversation.messages:
                if message.author and message.author.name == bot_username:
                    #logging.info(f"Bot has already commented in the conversation for u/{user.name}.")
                    return True  # Bot has already commented, so skip further review

            return False
        except Exception as e:
            logging.error(f"Error checking prior modmail conversations: {e}")
            return False

    # Add the HTML cleaning method using BeautifulSoup
    def clean_html(self, html_content):
        """
        Clean the HTML content by removing the boilerplate text and return the user-provided content.
        """
        # Use BeautifulSoup to parse the HTML and extract plain text
        soup = BeautifulSoup(html_content, "html.parser")
        cleaned_text = soup.get_text().strip()

        # List of boilerplate markers to remove
        boilerplate_markers = [
            "To approve this user, visit the approved users page for r/",
            "To get more information about this user, visit the profile page of u/"
        ]

        # Remove everything after the first occurrence of any boilerplate marker
        for marker in boilerplate_markers:
            if marker in cleaned_text:
                cleaned_text = cleaned_text.split(marker)[0].strip()
                break  # Stop after the first match is found

        return cleaned_text


    def truncate_text(self, text, max_length=50):
        """
        Truncate the text to the maximum number of words and append '...' if longer.
        """
        words = text.split()
        if len(words) > max_length:
            return ' '.join(words[:max_length]) + '...'
        return text
