from labscript import *
from labscript_devices.PulseBlaster import PulseBlaster

# Connection Table
PulseBlaster(name='pulseblaster_0', board_number=0)
DigitalOut(name='my_digital_out', parent_device=pulseblaster_0.direct_outputs, connection='flag 2')

#Experiment Logic
start()
my_digital_out.go_low(t=0)  # start low at the start
my_digital_out.go_high(t=1) # go high at 1s
stop(2)                     # stop at 2s