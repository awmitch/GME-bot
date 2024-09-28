# features/price_tracker.py

import time
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import pandas as pd
import pandas_market_calendars as mcal
import finnhub
import json
import os


class PriceTrackerFeature:
    def __init__(self, reddit, subreddit, finnhub_api_key, signature):
        self.reddit = reddit
        self.subreddit = subreddit
        self.scheduler = BackgroundScheduler()
        self.ticker_symbol = 'GME'  # GameStop's ticker symbol
        self.company_name = 'GameStop'  # Company name
        self.timezone = pytz.timezone('US/Eastern')  # Stock market timezone
        self.nyse = mcal.get_calendar('NYSE')  # NYSE market calendar
        self.finnhub_client = finnhub.Client(api_key=finnhub_api_key)
        self.signature = signature
        self.submission_id = None  # To keep track of the Reddit post ID
        self.weekly_data_file = 'weekly_data.json'  # JSON file to store weekly data

    def run(self, DEBUG=False):
        if DEBUG:
            self.create_or_update_post(create=True, DEBUG=DEBUG)
            return
        else:
            # Schedule the job for market open at 9:30 AM US Eastern time on trading days
            self.scheduler.add_job(
                self.create_or_update_post,
                'cron',
                day_of_week='mon-fri',
                hour=9,
                minute=30,
                timezone=self.timezone,
                args=[True]  # Create post
            )

            # Schedule updates every 30 minutes during market hours (10:00 AM to 3:30 PM)
            self.scheduler.add_job(
                self.create_or_update_post,
                'cron',
                day_of_week='mon-fri',
                hour='10-15',
                minute='0,30',
                timezone=self.timezone,
                args=[False]  # Update post
            )

            # Schedule final update at 4:00 PM
            self.scheduler.add_job(
                self.create_or_update_post,
                'cron',
                day_of_week='mon-fri',
                hour=16,
                minute=0,
                timezone=self.timezone,
                args=[False]  # Final update
            )

            # Schedule storing weekly open price on Monday at market open
            self.scheduler.add_job(
                self.store_weekly_open_price,
                'cron',
                day_of_week='mon',
                hour=9,
                minute=30,
                timezone=self.timezone
            )

            # Schedule posting weekly update on Friday at market close
            self.scheduler.add_job(
                self.post_weekly_update,
                'cron',
                day_of_week='fri',
                hour=16,
                minute=0,
                timezone=self.timezone
            )

            self.scheduler.start()
            logging.info("PriceTrackerFeature started and scheduler is running.")

            # Keep the thread alive
            try:
                while True:
                    time.sleep(1)
            except (KeyboardInterrupt, SystemExit):
                self.scheduler.shutdown()

    def create_or_update_post(self, create=False, DEBUG=False):
        try:
            # Get current date and time
            if DEBUG:
                # Force a specific date for debugging purposes
                debug_date = datetime.datetime.strptime("2024-09-23", '%Y-%m-%d').date()
                now = datetime.datetime.combine(debug_date, datetime.datetime.now().time(), self.timezone)
                today_str = debug_date.strftime('%Y-%m-%d')
            else:
                now = datetime.datetime.now(self.timezone)
                today_str = now.strftime('%Y-%m-%d')

            # Check if the market is open today
            market_date = now.date() if not DEBUG else debug_date  # Use debug_date in DEBUG mode
            if not self.is_market_open(market_date):
                logging.warning(f"Market closed on {today_str}. No data available.")
                return
            else:
                logging.info(f"Market is open on {today_str}. Proceeding with data fetch.")

            # Fetch the current quote data for the given ticker symbol using Finnhub
            quote = self.finnhub_client.quote(self.ticker_symbol)

            if not quote:  # No data returned
                logging.warning(f"No data fetched for {self.ticker_symbol}.")
                return

            # Extract required information from the Finnhub quote response
            current_price = quote['c']
            high_price = quote['h']
            low_price = quote['l']
            open_price = quote['o']
            previous_close_price = quote['pc']
            timestamp = pd.to_datetime(quote['t'], unit='s')

            # Calculate the percentage change based on the previous close
            dollar_change = current_price - previous_close_price
            percentage_change = ((current_price - previous_close_price) / previous_close_price) * 100

            # Format dollar change
            if abs(dollar_change) < 1:
                dollar_change_cents = abs(dollar_change) * 100
                dollar_change_formatted = f"{dollar_change:+.0f}¢"
            else:
                dollar_change_formatted = f"${dollar_change:+.2f}"

            # Determine the arrow for the percentage change
            arrow = '🟩' if percentage_change > 0 else '🔻'

            # Prepare the post title with the percentage change and dollar amount change
            percentage_change_formatted = f"{percentage_change:+.2f}%"
            title = f"{arrow} {percentage_change_formatted}/{dollar_change_formatted} - {self.company_name} Closing Price ${current_price:.2f} ({timestamp.strftime('%B %d, %Y')})"

            # Prepare the post content with the previous day's closing price
            content = f"""**{self.ticker_symbol} Daily Price Update for {timestamp.strftime('%B %d, %Y')}**
\n---\n
| Previous Close | Open | High | Low | Close |
|----------------|------|------|-----|-------|
| ${previous_close_price:.2f} | ${open_price:.2f} | ${high_price:.2f} | ${low_price:.2f} | ${current_price:.2f} |
"""

            # Append the signature to the content
            content += self.signature

            # Update weekly data in JSON file
            self.update_weekly_data({
                'date': timestamp.strftime('%Y-%m-%d'),
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': current_price
            })

            # Get the flair template ID
            choices = list(self.subreddit.flair.link_templates.user_selectable())
            template_id = next(x for x in choices if x["flair_text"] == "Discussion")["flair_template_id"]

            if create or self.submission_id is None:
                # Create the post
                if DEBUG:
                    submission = self.reddit.drafts.create(
                        title=title,
                        selftext=content,
                        flair_id=template_id,
                        subreddit=self.subreddit
                    )
                else:
                    submission = self.subreddit.submit(
                        title=title,
                        selftext=content,
                        flair_id=template_id
                    )
                self.submission_id = submission.id
                logging.info(f"Created new post for {now.strftime('%Y-%m-%d')}")
            else:
                # Fetch the submission
                submission = self.reddit.submission(id=self.submission_id)
                # Update the content
                submission.edit(content)
                # Update the title if needed
                submission.mod.update(title=title)
                logging.info(f"Updated post for {now.strftime('%Y-%m-%d')}")
        except Exception as e:
            logging.error(f"Error creating/updating post: {e}")

    def store_weekly_open_price(self):
        try:
            # Check if the market is open today
            now = datetime.datetime.now(self.timezone)
            market_date = now.date()
            if not self.is_market_open(market_date):
                logging.warning(f"Market closed on {market_date}. Cannot store weekly open price.")
                return

            # Fetch the current price
            quote = self.finnhub_client.quote(self.ticker_symbol)
            if not quote:
                logging.warning(f"No data fetched for {self.ticker_symbol}.")
                return

            open_price = quote['o']

            # Initialize weekly data
            weekly_data = {
                'open_price': open_price,
                'high_price': open_price,
                'low_price': open_price,
                'daily_data': []  # List to store daily high and low
            }

            # Store the data in a JSON file
            with open(self.weekly_data_file, 'w') as f:
                json.dump(weekly_data, f)

            logging.info(f"Stored weekly opening price: ${open_price:.2f}")
        except Exception as e:
            logging.error(f"Error storing weekly opening price: {e}")

    def update_weekly_data(self, daily_quote):
        try:
            # Read existing weekly data
            if os.path.exists(self.weekly_data_file):
                with open(self.weekly_data_file, 'r') as f:
                    weekly_data = json.load(f)
            else:
                # If the file doesn't exist, initialize it
                weekly_data = {
                    'open_price': daily_quote['open'],
                    'high_price': daily_quote['high'],
                    'low_price': daily_quote['low'],
                    'daily_data': []
                }

            # Update high and low prices
            weekly_data['high_price'] = max(weekly_data.get('high_price', daily_quote['high']), daily_quote['high'])
            weekly_data['low_price'] = min(weekly_data.get('low_price', daily_quote['low']), daily_quote['low'])

            # Append daily data
            weekly_data['daily_data'].append(daily_quote)

            # Write back to JSON file
            with open(self.weekly_data_file, 'w') as f:
                json.dump(weekly_data, f)

            logging.info("Updated weekly data with today's prices.")
        except Exception as e:
            logging.error(f"Error updating weekly data: {e}")

    def post_weekly_update(self):
        try:
            # Check if the market is open today
            now = datetime.datetime.now(self.timezone)
            market_date = now.date()
            if not self.is_market_open(market_date):
                logging.warning(f"Market closed on {market_date}. Cannot post weekly update.")
                return

            # Fetch the current price
            quote = self.finnhub_client.quote(self.ticker_symbol)
            if not quote:
                logging.warning(f"No data fetched for {self.ticker_symbol}.")
                return

            close_price = quote['c']

            # Read the weekly data from the JSON file
            if not os.path.exists(self.weekly_data_file):
                logging.error("Weekly data file not found.")
                return

            with open(self.weekly_data_file, 'r') as f:
                weekly_data = json.load(f)

            open_price = weekly_data['open_price']
            high_price = weekly_data['high_price']
            low_price = weekly_data['low_price']

            # Calculate weekly change
            dollar_change = close_price - open_price
            percentage_change = (dollar_change / open_price) * 100

            # Determine the arrow for the percentage change
            arrow = '🟩' if percentage_change > 0 else '🔻'

            # Format dollar change
            if abs(dollar_change) < 1:
                dollar_change_cents = abs(dollar_change) * 100
                dollar_change_formatted = f"{dollar_change:+.0f}¢"
            else:
                dollar_change_formatted = f"${dollar_change:+.2f}"

            percentage_change_formatted = f"{percentage_change:+.2f}%"

            # Prepare the post title
            title = f"{arrow} {percentage_change_formatted}/{dollar_change_formatted} - {self.company_name} Weekly Price Update ({now.strftime('%B %d, %Y')})"

            # Prepare the post content with weekly high and low
            content = f"""**{self.ticker_symbol} Weekly Price Update for Week Ending {now.strftime('%B %d, %Y')}**
\n---\n
| Open (Monday) | High | Low | Close (Friday) | Change |
|---------------|------|-----|----------------|--------|
| ${open_price:.2f} | ${high_price:.2f} | ${low_price:.2f} | ${close_price:.2f} | {percentage_change_formatted}/{dollar_change_formatted} |
"""

            # Append daily summaries
            content += "\n**Daily Summaries:**\n\n"
            content += "| Date | Open | High | Low | Close |\n"
            content += "|------|------|------|-----|-------|\n"
            for day in weekly_data['daily_data']:
                content += f"| {day['date']} | ${day['open']:.2f} | ${day['high']:.2f} | ${day['low']:.2f} | ${day['close']:.2f} |\n"

            # Append the signature to the content
            content += self.signature

            # Post to subreddit
            choices = list(self.subreddit.flair.link_templates.user_selectable())
            template_id = next(x for x in choices if x["flair_text"] == "Discussion")["flair_template_id"]
            self.subreddit.submit(title=title, selftext=content, flair_id=template_id)

            logging.info(f"Posted weekly price update for {now.strftime('%Y-%m-%d')}")

            # Remove the weekly data file after posting
            os.remove(self.weekly_data_file)
            logging.info("Cleared weekly data file after posting weekly update.")

        except Exception as e:
            logging.error(f"Error posting weekly update: {e}")

    def is_market_open(self, date):
        # Get the NYSE trading schedule for the specific date
        schedule = self.nyse.valid_days(start_date=date, end_date=date)

        # Check if the market is open on the given date (if schedule is not empty)
        return not schedule.empty

