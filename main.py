# main.py

import os
import threading
import logging
from rate_limiter import RateLimiter
import praw
import prawcore
from dotenv import load_dotenv

from features.cheers import CheersFeature
from features.price_tracker import PriceTrackerFeature
from features.entry_approval import EntryApprovalFeature

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RateLimitedRequestor(prawcore.Requestor):
    def __init__(self, *args, **kwargs):
        self.rate_limiter = kwargs.pop('rate_limiter')
        super().__init__(*args, **kwargs)

    def request(self, *args, **kwargs):
        self.rate_limiter.acquire()
        return super().request(*args, **kwargs)

def main():
    # Load environment variables from .env file
    load_dotenv()

    # Load Reddit credentials
    REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
    REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
    REDDIT_USERNAME = os.getenv('REDDIT_USERNAME')
    REDDIT_PASSWORD = os.getenv('REDDIT_PASSWORD')
    REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')

    # Load polygon credentials
    FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')

    # Load OpenAI API key for LangChain
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    # Subreddit to interact with
    SUBREDDIT_NAME = 'Gamestop_Enthusiasts'

    # Initialize the rate limiter
    rate_limiter = RateLimiter(max_calls=55, period=60)  # 55 calls per 60 seconds

    # Initialize Reddit API client
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT,
        requestor_class=RateLimitedRequestor,
        requestor_kwargs={'rate_limiter': rate_limiter}
    )

    # Define a signature
    signature = "\n\n---\n*Your boi Gimmy (GME) here. This is an automated bot. Contact u/Actual-Captain6649 for help.*"

    # Get subreddit instance
    subreddit = reddit.subreddit(SUBREDDIT_NAME)

    # Initialize features
    cheers_feature = CheersFeature(reddit, subreddit, signature)
    price_tracker_feature = PriceTrackerFeature(reddit, subreddit, FINNHUB_API_KEY, signature)
    entry_approval_feature = EntryApprovalFeature(reddit, subreddit, signature, OPENAI_API_KEY)

    # Run features in separate threads
    cheers_thread = threading.Thread(target=cheers_feature.run)
    price_tracker_thread = threading.Thread(target=price_tracker_feature.run)
    entry_approval_thread = threading.Thread(target=entry_approval_feature.run)

    cheers_thread.start()
    price_tracker_thread.start()
    entry_approval_thread.start()

    # Keep the main thread alive
    try:
        while True:
            pass
    except KeyboardInterrupt:
        logging.info("Shutting down bot...")

if __name__ == "__main__":
    main()
