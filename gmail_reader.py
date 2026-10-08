"""
gmail reader for nX-sig

the script will be written later, this docstring only describes what it should do

connect to a gmail account and wait for specific emails (e.g. trade
confirmations from the broker) to collect transactions info from them:
stock, BUY/SELL, count and price.

the collected transactions are then recorded with
nx_sig_db.transactions_add_one(stock, transaction_type, count, price),
so they don't have to be entered manually with 'tr add'.

account credentials should be kept in .env, not in the code.
"""
