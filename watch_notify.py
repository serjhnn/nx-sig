# notification server for a Garmin watch
#
# the script will be written later, this file only describes the idea
#
# Garmin Connect IQ SDK allows watch apps to call external web APIs
# (Communications.makeWebRequest, the request goes through the paired phone),
# so a watch app can poll this server for new notifications and send
# quick actions back to it.
#
# notifications:
#   there can be different types of notifications (e.g. price alerts,
#   strategy signals, transaction confirmations).
#   on the watch they should be short and precise, so they can be read
#   at a glance and acted on quickly (e.g. confirm / dismiss).
