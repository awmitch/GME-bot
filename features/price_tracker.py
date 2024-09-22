# features/price_tracker.py

import time
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import pandas as pd
import pandas_market_calendars as mcal
from polygon import RESTClient


DEBUG = False

class PriceTrackerFeature:
    def __init__(self, reddit, subreddit, polygon_api_key):
        self.reddit = reddit
        self.subreddit = subreddit
        self.scheduler = BackgroundScheduler()
        self.ticker_symbol = 'GME'  # GameStop's ticker symbol
        self.timezone = pytz.timezone('US/Eastern')  # Stock market timezone
        self.nyse = mcal.get_calendar('NYSE')  # NYSE market calendar
        self.client = RESTClient(polygon_api_key)
        
        self.signature = signature

    def run(self):
        # Schedule the job for 4:30 PM US Eastern time on trading days
        self.scheduler.add_job(
            self.post_daily_update,
            'cron',
            day_of_week='mon-fri',
            hour=16,
            minute=30,
            timezone=self.timezone
        )
        if (DEBUG):
            self.post_daily_update()
            return
        else:
            self.scheduler.start()

        logging.info("PriceTrackerFeature started and scheduler is running.")

        # Keep the thread alive
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()

    def post_daily_update(self):
        try:
            # Get current date and time
            if DEBUG:
                # Force a specific date for debugging purposes
                debug_date = datetime.datetime.strptime("2024-09-20", '%Y-%m-%d').date()
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

            # Define the date range
            start_date = now - datetime.timedelta(days=5)
            end_date = now

            # Fetch stock data for the last 5 trading days using Polygon.io
            aggs = self.client.get_aggs(self.ticker_symbol, 1, "day", start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))

            if not aggs:  # No data returned
                logging.warning("No data fetched for GME.")
                return

            # Convert the Agg list to a pandas DataFrame for easier manipulation
            data = pd.DataFrame([{
                'open': agg.open,
                'high': agg.high,
                'low': agg.low,
                'close': agg.close,
                'volume': agg.volume,
                'timestamp': pd.to_datetime(agg.timestamp, unit='ms')
            } for agg in aggs])

            # Set the timestamp as the index and adjust the timezone
            data.set_index('timestamp', inplace=True)
            data.index = data.index.tz_localize('UTC').tz_convert(self.timezone)

            # Compare the date properly with the index
            if today_str in data.index.strftime('%Y-%m-%d').tolist():
                last_row = data.loc[data.index.strftime('%Y-%m-%d') == today_str].iloc[0]
            else:
                # Handle missing data more gracefully with extra logging
                available_dates = data.index.strftime('%Y-%m-%d').tolist()
                logging.warning(f"No data available for {today_str}. Available dates are: {available_dates}")
                return

            # Extract required information
            open_price = last_row['open']
            high_price = last_row['high']
            low_price = last_row['low']
            close_price = last_row['close']
            volume = int(last_row['volume'])

            # Calculate the percentage change
            percentage_change = ((close_price - open_price) / open_price) * 100

            # Determine the arrow for the percentage change
            if percentage_change > 0:
                arrow = '🟩'
            else:
                arrow = '🔻'

            # Prepare the post title with the percentage change
            title = f"GME Daily Price Update {arrow} {abs(percentage_change):.2f}% - {now.strftime('%Y-%m-%d')}"

            # Prepare the post content
            content = f"""**GME Daily Price Update for {now.strftime('%B %d, %Y')}**
\n---\n
| Open | High | Low | Close | Volume |
|------|------|-----|-------|--------|
| ${open_price:.2f} | ${high_price:.2f} | ${low_price:.2f} | ${close_price:.2f} | {volume:,} |


"""

            # If it's the last trading day of the week, include weekly stats
            if self.is_last_trading_day_of_week(now.date()):
                weekly_data = data

                weekly_open = data['open'].iloc[0]
                weekly_high = data['high'].max()
                weekly_low = data['low'].min()
                weekly_close = data['close'].iloc[-1]
                weekly_volume = int(data['volume'].sum())

                content += f"""\n\n---\n**Weekly Summary**

| Open | High | Low | Close | Volume |
|------|------|-----|-------|--------|
| ${weekly_open:.2f} | ${weekly_high:.2f} | ${weekly_low:.2f} | ${weekly_close:.2f} | {weekly_volume:,} |
"""

            # Append the signature to the content
            content += self.signature

            # Post to subreddit
            choices = list(self.subreddit.flair.link_templates.user_selectable())
            template_id = next(x for x in choices if x["flair_text"] == "Discussion")["flair_template_id"]
            if (DEBUG):
                draft = self.reddit.drafts.create(
                    title=title,
                    selftext=content,
                    flair_id=template_id,
                    subreddit=self.subreddit
                )
            else:
                self.subreddit.submit(title=title, selftext=content, flair_id=template_id)
                
            logging.info(f"Posted daily price update for {now.strftime('%Y-%m-%d')}")
        except Exception as e:
            logging.error(f"Error posting daily update: {e}")

    def is_market_open(self, date):
        # Get the NYSE trading schedule for the specific date
        schedule = self.nyse.valid_days(start_date=date, end_date=date)

        # Check if the market is open on the given date (if schedule is not empty)
        return not schedule.empty


    def is_last_trading_day_of_week(self, date):
        # Check if today is Friday
        return date.weekday() == 4  # 0 = Monday, ..., 4 = Friday
