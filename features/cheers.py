# features/cheers.py

import os
import time
import json
import logging
import threading
import re
from datetime import datetime, timedelta

class CheersFeature:
    def __init__(self, reddit, subreddit, signature):
        self.reddit = reddit
        self.subreddit = subreddit

        # Data files
        self.CHEERS_FILE = 'cheers_data.json'
        self.RATE_LIMIT_FILE = 'rate_limit.json'
        self.CHEERS_AWARDED_FILE = 'cheers_awarded_data.json'
        self.LAST_WEEKLY_POST_FILE = 'last_weekly_post.txt'

        # Constants for security
        self.MIN_ACCOUNT_AGE_DAYS = 7
        self.MIN_COMMENT_KARMA = 50
        self.CHEERS_COOLDOWN_SECONDS = 3600/6  # 10 minutes

        self.REDDIT_USERNAME = self.reddit.user.me().name

        # Load data
        self.lock = threading.Lock()
        self.cheers_data = self.load_json_data(self.CHEERS_FILE)
        self.rate_limit_data = self.load_json_data(self.RATE_LIMIT_FILE)
        self.cheers_awarded_data = self.load_json_data(self.CHEERS_AWARDED_FILE)
        self.last_weekly_post_time = self.load_last_weekly_post_time()

        self.signature = signature

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

    def load_last_weekly_post_time(self):
        if os.path.exists(self.LAST_WEEKLY_POST_FILE):
            with open(self.LAST_WEEKLY_POST_FILE, 'r') as f:
                timestamp = f.read()
                return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        else:
            return None

    def save_last_weekly_post_time(self):
        with open(self.LAST_WEEKLY_POST_FILE, 'w') as f:
            f.write(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))

    def update_user_flair(self, username, cheers_count):
        # Fetch the user's existing flair
        existing_flair = self.subreddit.flair(username)
        flair_text = ''
        flair_css_class = ''
        for flair in existing_flair:
            flair_text = flair['flair_text'] or ''
            flair_css_class = flair['flair_css_class'] or ''

        # Remove any existing cheers count from the flair
        flair_text = re.sub(r'\(:1DFV1:\d+\)$', '', flair_text).strip()

        # Append the new cheers count using the emoji
        new_flair_text = f"{flair_text} (:1DFV1:{cheers_count})".strip()

        # Ensure the flair text doesn't exceed Reddit's limit (64 characters)
        if len(new_flair_text) > 64:
            allowed_length = 64 - len(f" (:1DFV1:{cheers_count})")
            flair_text = flair_text[:allowed_length].rstrip()
            new_flair_text = f"{flair_text} (:1DFV1:{cheers_count})"

        # Update the user's flair
        self.subreddit.flair.set(username, text=new_flair_text, css_class=flair_css_class)
        logging.info(f"Updated flair for {username}: {new_flair_text}")

    def can_award_cheers(self, author):
        current_time = datetime.utcnow()
        author_name = author.name

        # Rate limiting check
        last_award_time_str = self.rate_limit_data.get(author_name)
        if last_award_time_str:
            last_award_time = datetime.strptime(last_award_time_str, "%Y-%m-%d %H:%M:%S")

            if (current_time - last_award_time).total_seconds() < self.CHEERS_COOLDOWN_SECONDS:
                return False, "You can only award cheers once every 10 minutes."

        # Account age check
        account_age_days = (current_time - datetime.utcfromtimestamp(author.created_utc)).days
        if account_age_days < self.MIN_ACCOUNT_AGE_DAYS:
            return False, f"Your account must be at least {self.MIN_ACCOUNT_AGE_DAYS} days old to award cheers."

        # Karma check
        if author.comment_karma < self.MIN_COMMENT_KARMA:
            return False, f"You need at least {self.MIN_COMMENT_KARMA} comment karma to award cheers."

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

    def handle_cheers(self, mentioned_username, awarder, comment, reason_text):
        author_name = awarder.name

        # Remove 'u/' prefix from the mentioned username if present
        mentioned_username = mentioned_username.lstrip('u/').lstrip('/')

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

        if mentioned_username.lower() == author_name.lower():
            content = "You cannot award cheers to yourself!"
            content += self.signature
            comment.reply(content)
            logging.info(f"{author_name} tried to award cheers to themselves.")
            return

        # Security checks
        can_award, message = self.can_award_cheers(awarder)
        if not can_award:
            content = message
            content += self.signature
            comment.reply(content)
            logging.info(f"{author_name} failed security checks: {message}")
            return

        # Update rate limit data
        self.rate_limit_data[author_name] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.save_json_data(self.rate_limit_data, self.RATE_LIMIT_FILE)

        # If all checks pass, proceed with awarding cheers
        with self.lock:
            # Update cheers data for the recipient
            cheers_count = self.cheers_data.get(mentioned_username.lower(), 0) + 1
            self.cheers_data[mentioned_username.lower()] = cheers_count
        self.save_json_data(self.cheers_data, self.CHEERS_FILE)

        # Update cheers awarded data for the awarder
        self.cheers_awarded_data[author_name.lower()] = self.cheers_awarded_data.get(author_name.lower(), 0) + 1
        self.save_json_data(self.cheers_awarded_data, self.CHEERS_AWARDED_FILE)

        # Update flair
        self.update_user_flair(mentioned_username, cheers_count)

        # Reply to the comment
        content = f"u/{author_name} has awarded cheers to u/{mentioned_username}! They now have {cheers_count} cheers.{reason_text}"
        content += self.signature
        comment.reply(content)
        logging.info(f"cheers awarded to {mentioned_username} by {author_name}.")

    def process_cheers_command(self, comment, command_text):
        words = command_text.strip().split()
        awarder = comment.author
        author_name = awarder.name

        # Check for '!cheers me' or '!cheers top'
        if len(words) >= 2 and words[1].lower() == 'me':
            # Handle '!cheers me'
            cheers_count = self.cheers_data.get(author_name.lower(), 0)
            content = f"You have {cheers_count} cheers."
            content += self.signature
            comment.reply(content)
            logging.info(f"Replied to {author_name} with their cheers count.")
            return
        elif len(words) >= 2 and words[1].lower() == 'top':
            # Handle '!cheers top'
            top_users = sorted(self.cheers_data.items(), key=lambda x: x[1], reverse=True)[:5]
            leaderboard = '\n'.join([f"{idx+1}. u/{user} - {count} cheers" for idx, (user, count) in enumerate(top_users)])
            content = f"**Cheers Leaderboard:**\n\n{leaderboard}"
            content += self.signature
            comment.reply(content)
            logging.info(f"Provided leaderboard to {author_name}.")
            return

        # Check if the second word is 'to', skip it
        idx = 1
        if len(words) > idx and words[idx].lower() == 'to':
            idx += 1

        if len(words) > idx:
            mentioned_username = words[idx]
            reason = ' '.join(words[idx+1:]).strip()
        else:
            # No username provided, award cheers to parent comment's author
            parent = comment.parent()
            if hasattr(parent, 'author') and parent.author:
                mentioned_username = parent.author.name
                reason = ''
            else:
                content = "Cannot find the user to award cheers to."
                content += self.signature
                comment.reply(content)
                return

        # Remove 'u/' prefix if present
        mentioned_username = mentioned_username.lstrip('u/').lstrip('/')

        # Now handle the cheers
        reason_text = f'\n\n"*{reason}*"' if reason else ""
        self.handle_cheers(mentioned_username, awarder, comment, reason_text)

    def monitor_comments(self):
        for comment in self.subreddit.stream.comments(skip_existing=True):
            try:
                if comment.author.name == self.REDDIT_USERNAME:
                    continue

                if re.search(r'\b!cheers\b', comment.body, re.IGNORECASE):
                    command_match = re.search(r'(?i)(!cheers\b.*)', comment.body)
                    if command_match:
                        command_text = command_match.group(1)
                        self.process_cheers_command(comment, command_text)

            except Exception as e:
                logging.error(f"An error occurred while processing a comment: {e}")
                continue

    def post_weekly_update(self):
        # Prepare the leaderboard content for cheers recipients
        top_recipients = sorted(self.cheers_data.items(), key=lambda x: x[1], reverse=True)[:10]
        recipient_leaderboard = '\n'.join([f"{idx+1}. u/{user} - {count} cheers" for idx, (user, count) in enumerate(top_recipients)])

        # Prepare the leaderboard content for cheers awarders
        top_awarders = sorted(self.cheers_awarded_data.items(), key=lambda x: x[1], reverse=True)[:10]
        awarders_leaderboard = '\n'.join([f"{idx+1}. u/{user} - {count} cheers awarded" for idx, (user, count) in enumerate(top_awarders)])

        content = f"**Cheers Leaderboard (Recipients):**\n\n{recipient_leaderboard}\n\n"
        content += f"**Top Cheers Givers:**\n\n{awarders_leaderboard}\n\n"

        # Instructions on how to use the cheers feature
        instructions = (
            "You can award cheers to fellow community members by commenting:\n\n"
            "- `!cheers u/username` - award cheers to a user\n"
            "- `!cheers me` - see how many cheers you have\n"
            "- `!cheers top` - see the top users with the most cheers\n"
            "- `!cheers` - award cheers to the user you are replying to\n\n"
            "Cheers help recognize and appreciate valuable contributions in our community!"
        )
        content += instructions
        content += self.signature

        # Post the content to the subreddit
        self.subreddit.submit(title="Weekly Cheers Leaderboard and Instructions", selftext=content)
        logging.info("Posted the weekly cheers leaderboard and instructions.")

    def run(self):
        logging.info("Starting to monitor comments for cheers commands...")
        while True:
            try:
                # Check if it's time to post the weekly update
                current_time = datetime.utcnow()
                if self.last_weekly_post_time is None or (current_time - self.last_weekly_post_time).days >= 7:
                    self.post_weekly_update()
                    self.last_weekly_post_time = current_time
                    self.save_last_weekly_post_time()

                self.monitor_comments()
            except Exception as e:
                logging.error(f"An error occurred: {e}")
                time.sleep(60)  # Wait before retrying
