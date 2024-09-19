# reddit_bot.py

import os
import time
import tweepy
import praw
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

# Load Twitter credentials
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')

# Load Reddit credentials
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USERNAME = os.getenv('REDDIT_USERNAME')
REDDIT_PASSWORD = os.getenv('REDDIT_PASSWORD')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')

# Twitter user accounts to monitor
TWITTER_USERNAMES = ['larryvc', 'ryancohen', 'TheRoaringKitty']

# Subreddit to post to
SUBREDDIT_NAME = 'Gamestop_Enthusiasts'

def main():
    # Initialize Twitter API client
    twitter_auth = tweepy.OAuth1UserHandler(
        TWITTER_API_KEY,
        TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_SECRET
    )
    twitter_api = tweepy.API(twitter_auth)

    # Initialize Reddit API client
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT
    )

    # Dictionary to store the last post IDs
    last_post_ids = {}

    while True:
        for username in TWITTER_USERNAMES:
            since_id = last_post_ids.get(username)
            try:
                posts = twitter_api.user_timeline(
                    screen_name=username,
                    since_id=since_id,
                    post_mode='extended',
                    exclude_replies=True,
                    include_rts=False
                )
                if posts:
                    # Process posts in reverse chronological order
                    for post in reversed(posts):
                        post_text = post.full_text
                        post_url = f"https://x.com/{username}/status/{post.id}"
                        title = f"New X from {username}: {post_text[:300]}"

                        # Post to Reddit
                        subreddit = reddit.subreddit(SUBREDDIT_NAME)
                        subreddit.submit(title=title, url=post_url)
                        logging.info(f"Posted new X from {username} to Reddit.")

                        # Update the last processed post ID
                        last_post_ids[username] = post.id
                else:
                    logging.info(f"No new Xs found for {username}.")
            except Exception as e:
                logging.error(f"Error fetching Xs for {username}: {e}")
        # Wait before checking again
        time.sleep(300)  # 5 minutes

if __name__ == "__main__":
    main()
