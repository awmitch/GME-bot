# features/kudos.py

import os
import time
import json
import logging
from datetime import datetime, timedelta

class KudosFeature:
    def __init__(self, reddit, subreddit, signature):
        self.reddit = reddit
        self.subreddit = subreddit

        # Data files
        self.KUDOS_FILE = 'kudos_data.json'
        self.RATE_LIMIT_FILE = 'rate_limit.json'

        # Constants for security
        self.MIN_ACCOUNT_AGE_DAYS = 7
        self.MIN_COMMENT_KARMA = 50
        self.KUDOS_COOLDOWN_SECONDS = 3600/6  # 10 minutes

        self.REDDIT_USERNAME = self.reddit.user.me().name

        # Load data
        self.kudos_data = self.load_json_data(self.KUDOS_FILE)
        self.rate_limit_data = self.load_json_data(self.RATE_LIMIT_FILE)

        self.signature = signature

    def load_json_data(self, file_name):
        if os.path.exists(file_name):
            with open(file_name, 'r') as f:
                return json.load(f)
        else:
            return {}

    def save_json_data(self, data, file_name):
        with open(file_name, 'w') as f:
            json.dump(data, f)

    def update_user_flair(self, username, kudos_count):
        # Fetch the user's existing flair
        existing_flair = self.subreddit.flair(username)
        flair_text = ''
        flair_css_class = ''
        for flair in existing_flair:
            flair_text = flair['flair_text'] or ''
            flair_css_class = flair['flair_css_class'] or ''

        # Remove any existing kudos count from the flair
        import re
        flair_text = re.sub(r'\(🎖\d+\)$', '', flair_text).strip()

        # Append the new kudos count using the emoji
        new_flair_text = f"{flair_text} (🎖{kudos_count})".strip()

        # Ensure the flair text doesn't exceed Reddit's limit (64 characters)
        if len(new_flair_text) > 64:
            allowed_length = 64 - len(f" (🎖{kudos_count})")
            flair_text = flair_text[:allowed_length].rstrip()
            new_flair_text = f"{flair_text} (🎖{kudos_count})"

        # Update the user's flair
        self.subreddit.flair.set(username, text=new_flair_text, css_class=flair_css_class)
        logging.info(f"Updated flair for {username}: {new_flair_text}")

    def can_award_kudos(self, author):
        current_time = datetime.utcnow()
        author_name = author.name

        # Rate limiting check
        last_award_time_str = self.rate_limit_data.get(author_name)
        if last_award_time_str:
            last_award_time = datetime.strptime(last_award_time_str, "%Y-%m-%d %H:%M:%S")
            if (current_time - last_award_time).total_seconds() < self.KUDOS_COOLDOWN_SECONDS:
                return False, "You can only award kudos once every 10 minutes."

        # Account age check
        account_age_days = (current_time - datetime.utcfromtimestamp(author.created_utc)).days
        if account_age_days < self.MIN_ACCOUNT_AGE_DAYS:
            return False, f"Your account must be at least {self.MIN_ACCOUNT_AGE_DAYS} days old to award kudos."

        # Karma check
        if author.comment_karma < self.MIN_COMMENT_KARMA:
            return False, f"You need at least {self.MIN_COMMENT_KARMA} comment karma to award kudos."

        return True, ""

    def is_valid_reddit_user(self, username):
        try:
            user = self.reddit.redditor(username)
            # Try fetching the user's attributes to see if they exist
            user.id  # Accessing the id attribute will raise an exception if the user doesn't exist
            return True
        except Exception as e:
            logging.error(f"Reddit user {username} does not exist: {e}")
            return False

    def is_user_part_of_subreddit(self, username):
        try:
            # Fetch the redditor object for the given username
            user = self.reddit.redditor(username)
            
            # Check if the user has made any submissions in the subreddit
            submissions = list(user.submissions.new(limit=10))
            for submission in submissions:
                if submission.subreddit.display_name.lower() == self.subreddit.display_name.lower():
                    return True

            # Check if the user has commented in the subreddit
            comments = list(user.comments.new(limit=10))
            for comment in comments:
                if comment.subreddit.display_name.lower() == self.subreddit.display_name.lower():
                    return True

            # If neither submissions nor comments in the subreddit are found, return False
            return False

        except Exception as e:
            logging.error(f"Failed to check subreddit membership for {username}: {e}")
            return False


    def handle_kudos(self, mentioned_username, awarder, comment):
        author_name = awarder.name

        # Ensure the mentioned username is valid
        if not mentioned_username.startswith('u/'):
            content = (
                "Invalid username format. Please use 'u/username' to mention a Reddit user.\n\n"
                "Other commands include:\n\n"
                "`!kudos me` - see your own kudos\n\n"
                "`!kudos top` - see the leaderboard"
            )
            content += self.signature
            comment.reply(content)
            logging.info(f"{author_name} used invalid format for mentioning a user: {mentioned_username}")
            return

        # Strip 'u/' prefix from the mentioned username
        mentioned_username = mentioned_username[2:]

        # Check if the mentioned username exists
        if not self.is_valid_reddit_user(mentioned_username):
            content = f"User u/{mentioned_username} does not exist on Reddit."
            content += self.signature
            comment.reply(content)
            logging.info(f"{author_name} mentioned non-existent user: {mentioned_username}")
            return

        # Check if the mentioned user is part of the subreddit
        if not self.is_user_part_of_subreddit(mentioned_username):
            content = f"User u/{mentioned_username} is not active in this subreddit."
            content += self.signature
            comment.reply(content)
            logging.info(f"{author_name} mentioned a user not part of the subreddit: {mentioned_username}")
            return

        # If all checks pass, proceed with awarding kudos
        kudos_count = self.kudos_data.get(mentioned_username, 0) + 1
        self.kudos_data[mentioned_username] = kudos_count
        self.save_json_data(self.kudos_data, self.KUDOS_FILE)

        # Update flair
        self.update_user_flair(mentioned_username, kudos_count)

        # Reply to the comment
        content = f"u/{author_name} has awarded kudos to u/{mentioned_username}! They now have {kudos_count} kudos."
        content += self.signature
        comment.reply(content)
        logging.info(f"Kudos awarded to {mentioned_username} by {author_name}.")

    def monitor_comments(self):
        for comment in self.subreddit.stream.comments(skip_existing=True):
            try:
                if comment.author.name == self.REDDIT_USERNAME:
                    continue

                body = comment.body.strip().lower()
                if body.startswith('!kudos'):
                    words = comment.body.strip().split()
                    awarder = comment.author
                    author_name = awarder.name

                    # Handle '!kudos me' command
                    if len(words) == 2 and words[1].lower() == 'me':
                        kudos_count = self.kudos_data.get(author_name, 0)
                        content = f"You have {kudos_count} kudos."
                        content += self.signature
                        comment.reply(content)
                        logging.info(f"Replied to {author_name} with their kudos count.")
                        continue

                    # Handle '!kudos top' command
                    if len(words) == 2 and words[1].lower() == 'top':
                        top_users = sorted(self.kudos_data.items(), key=lambda x: x[1], reverse=True)[:5]
                        leaderboard = '\n'.join([f"{idx+1}. u/{user} - {count} kudos" for idx, (user, count) in enumerate(top_users)])
                        content = f"**Kudos Leaderboard:**\n\n{leaderboard}"
                        content += self.signature
                        comment.reply(content)
                        logging.info(f"Provided leaderboard to {author_name}.")
                        continue

                    if len(words) >= 2:
                        mentioned_username = words[1]
                        self.handle_kudos(mentioned_username, awarder, comment)

            except Exception as e:
                logging.error(f"An error occurred while processing a comment: {e}")
                continue


    def run(self):
        logging.info("Starting to monitor comments for kudos commands...")
        while True:
            try:
                self.monitor_comments()
            except Exception as e:
                logging.error(f"An error occurred: {e}")
                time.sleep(60)  # Wait before retrying
