import usb_cdc

# Keep the REPL/console on the primary USB serial channel, and open a second,
# protocol-only "data" channel for the Pi's led-controller service to talk on --
# keeps our JSON-line protocol from ever colliding with CircuitPython's own
# REPL output/tracebacks on the console channel.
usb_cdc.enable(console=True, data=True)
