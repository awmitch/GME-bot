# features/quips.py

import os
import time
import json
import logging
import threading
import re
from datetime import datetime
import praw
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate


class QuipsFeature:
    def __init__(self, reddit, subreddit, signature, openai_api_key):
        self.reddit = reddit
        self.subreddit = subreddit
        self.signature = signature
        self.REDDIT_USERNAME = self.reddit.user.me().name

        # Initialize LLM
        self.llm = ChatOpenAI(
            model="gpt-4o",
            openai_api_key=openai_api_key,
            max_tokens=200  # Limit the response length
        )
        self.prompt_template = PromptTemplate(
            input_variables=["user_comment", "parent_comment"],
            template=(
                "You are GME-Bot, a helpful, informative, and sometimes cheeky Reddit bot for the GameStop subreddit. "
                "When someone replies to you or mentions '!gimmy', you respond appropriately in the context of the GameStop community. "
                "The user's comment is: \"{user_comment}\" "
                "{parent_comment}"
                "Provide a brief, relevant reply as GME-Bot."
            )
        )
        self.llm_chain = self.prompt_template | self.llm

        # Rate limiting
        self.RATE_LIMIT_FILE = 'quips_rate_limit.json'
        self.COOLDOWN_SECONDS = 600  # 10 minutes
        self.lock = threading.Lock()
        self.rate_limit_data = self.load_json_data(self.RATE_LIMIT_FILE)

    def load_json_data(self, file_name):
        with self.lock:
            if os.path.exists(file_name):
                with open(file_name, 'r') as f:
                    return json.load(f)
            else:
                return {}

    def save_json_data(self, data, file_name):
        with self.lock:
            with open(file_name, 'w') as f:
                json.dump(data, f)

    def monitor_comments(self):
        logging.info("Starting to monitor comments for quips...")
        for comment in self.subreddit.stream.comments(skip_existing=True):
            try:
                if comment.author.name == self.REDDIT_USERNAME:
                    continue

                # Check if the comment is a reply to a post or comment made by the bot
                parent = comment.parent()
                is_reply_to_bot = False
                if isinstance(parent, praw.models.Comment) or isinstance(parent, praw.models.Submission):
                    if parent.author and parent.author.name == self.REDDIT_USERNAME:
                        is_reply_to_bot = True

                # Check if the comment contains '!gimmy' (case-insensitive)
                contains_gimmy = re.search(r'!gimmy', comment.body, re.IGNORECASE) is not None

                # Check if the comment invokes the cheers command
                invokes_cheers = re.search(r'!cheers', comment.body, re.IGNORECASE) is not None

                # If the comment is a reply to the bot or contains '!gimmy', and does not invoke '!cheers'
                if (is_reply_to_bot or contains_gimmy) and not invokes_cheers:
                    self.process_comment(comment)
            except Exception as e:
                logging.error(f"An error occurred while processing a comment: {e}")
                continue

    def process_comment(self, comment):
        author_name = comment.author.name
        current_time = datetime.utcnow()

        # Rate limiting check
        last_response_time_str = self.rate_limit_data.get(author_name)
        if last_response_time_str:
            last_response_time = datetime.strptime(last_response_time_str, "%Y-%m-%d %H:%M:%S")
            if (current_time - last_response_time).total_seconds() < self.COOLDOWN_SECONDS:
                logging.info(f"User {author_name} is on cooldown.")
                # Calculate how much time remains
                time_remaining = int((self.COOLDOWN_SECONDS - time_since_last_response) // 60) + 1
                response_content = (
                    f"Sorry u/{author_name}, you can only request a response every 10 minutes. "
                    f"Please wait {time_remaining} more minute(s)."
                )
                response_content += self.signature
                # Reply to the comment
                try:
                    comment.reply(response_content)
                    logging.info(f"Informed {author_name} about cooldown.")
                except Exception as e:
                    logging.error(f"Failed to reply to {author_name} about cooldown: {e}")
                return  # Do not proceed further

        # Update rate limit data
        self.rate_limit_data[author_name] = current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_json_data(self.rate_limit_data, self.RATE_LIMIT_FILE)

        user_content = comment.body

        # Limit the length of user_content to prevent abuse
        max_input_length = 500  # Adjust as needed
        if len(user_content) > max_input_length:
            user_content = user_content[:max_input_length]

        # Get parent comment's body if available and not too long
        parent_content = ""
        parent = comment.parent()
        if isinstance(parent, praw.models.Comment):
            parent_body = parent.body
            max_parent_length = 500  # Adjust as needed
            if len(parent_body) > max_parent_length:
                parent_body = parent_body[:max_parent_length]
            parent_content = parent_body
        elif isinstance(parent, praw.models.Submission):
            parent_title = parent.title
            max_parent_length = 500  # Adjust as needed
            if len(parent_title) > max_parent_length:
                parent_title = parent_title[:max_parent_length]
            parent_content = parent_title

        # Prepare the parent comment section for the prompt
        if parent_content:
            parent_content = f'The parent comment is: "{parent_content}" '
        else:
            parent_content = ""

        # Prepare the prompt and get the response
        try:
            response = self.llm_chain.invoke({
                "user_comment": user_content,
                "parent_comment": parent_content,
            })
            response_content = response.content
        except Exception as e:
            logging.error(f"An error occurred while invoking LLM: {e}")
            return

        # Limit the length of the response
        max_output_length = 500  # Adjust as needed
        if len(response_content) > max_output_length:
            response_content = response_content[:max_output_length]

        # Append signature
        response_content += self.signature

        # Reply to the comment
        try:
            comment.reply(response_content)
            logging.info(f"Replied to comment by {author_name}")
        except Exception as e:
            logging.error(f"Failed to reply to comment by {author_name}: {e}")

    def run(self):
        while True:
            try:
                self.monitor_comments()
            except Exception as e:
                logging.error(f"An error occurred: {e}")
                time.sleep(60)  # Wait before retrying
