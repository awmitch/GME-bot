# main.py

import os
import threading
import logging
import praw
from dotenv import load_dotenv

from features.kudos import KudosFeature
from features.price_tracker import PriceTrackerFeature

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def main():
    # Load environment variables from .env file
    load_dotenv()

    # Load Reddit credentials
    REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
    REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
    REDDIT_USERNAME = os.getenv('REDDIT_USERNAME')
    REDDIT_PASSWORD = os.getenv('REDDIT_PASSWORD')
    REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')

    # Load polygol credentials
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY')

    # Subreddit to interact with
    SUBREDDIT_NAME = 'Gamestop_Enthusiasts'

    # Initialize Reddit API client
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT
    )

    # Define a signature
    signature = "\n\n---\n*Your boi Gimmy (GME) here. This is an automated bot. Contact u/Actual-Captain6649 for help.*"

    # Get subreddit instance
    subreddit = reddit.subreddit(SUBREDDIT_NAME)

    # Initialize features
    kudos_feature = KudosFeature(reddit, subreddit, signature)
    price_tracker_feature = PriceTrackerFeature(reddit, subreddit, POLYGON_API_KEY, signature)

    # Run features in separate threads
    kudos_thread = threading.Thread(target=kudos_feature.run)
    price_tracker_thread = threading.Thread(target=price_tracker_feature.run)

    kudos_thread.start()
    price_tracker_thread.start()

    # Keep the main thread alive
    try:
        while True:
            pass
    except KeyboardInterrupt:
        logging.info("Shutting down bot...")

if __name__ == "__main__":
    main()
