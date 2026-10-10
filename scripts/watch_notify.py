# notification server for a Garmin watch
#
# the script will be written later, this file only describes
# the idea
#
# Garmin Connect IQ SDK allows watch apps to call external
# web APIs (Communications.makeWebRequest, the request goes
# through the paired phone), so a watch app can poll this
# server for new notifications and send quick actions back
# to it.
#
# notifications:
#   there can be different types of notifications (e.g.
#   price alerts, strategy signals, transaction
#   confirmations). on the watch they should be short and
#   precise, so they can be read at a glance and acted on
#   quickly (e.g. confirm / dismiss).
#
# server location (to be checked):
#   maybe the watch app can call localhost (127.0.0.1) on
#   the paired phone, and that request can be redirected to
#   a web server running in Termux, so no external server
#   would be needed. check that Connect IQ really allows
#   requests to localhost, and whether plain http is
#   accepted there or https is required.
#
# background polling:
#   Connect IQ SDK has a background service
#   (System.ServiceDelegate) that runs even when the app is
#   not open. it can be scheduled with
#   Background.registerForTemporalEvent() to periodically
#   poll this server (the minimum interval is 5 minutes),
#   and pass new notifications to the app with
#   Background.exit(data), or ask the user to open the app
#   with Background.requestApplicationWake(message).
#   background code has a small memory limit, so server
#   responses should be small (short text, few fields).
