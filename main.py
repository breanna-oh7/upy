# this is a translation of ao27.pio and ao27.c by Michael Wyrick
# pioasm was used to double check
import sys 
from machine import UART
import _thread
from machine import Pin, mem32
import machine
import rp2
from time import sleep_ms, sleep, ticks_us, ticks_diff

# ------------------------------------
#
#  PIO 0 sm
#
# ------------------------------------

# ------------------------------------
# Generate the Receive Clock PLL running 16x the baud rate.  Can add, subtract  one 1/16th clock per baud,  or stay the same
#   SM needs to be set to run 16 times the baud rate
#   Set interrupt 0 on on sample clock edge
#   In Pins: data in (1 bit)
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pings: n/a
#   Side pins: 
#          pin 0 = Subtract phase       # Signal that we subtracted a phase
#          pin 1 = add phase            # Signal that we inserted a phase
# ------------------------------------
@rp2.asm_pio(sideset_init=[rp2.PIO.OUT_LOW] * 2)
def rxclock(): # clcokdiv 8125
    wrap_target()

    label("sub")
    nop()                          .side(1)            # delay one clock
    
    label("cont")           
    mov(x, pins)                   .side(0)[4]         # Get the input and wait a few clock
    mov(y, pins)                   .side(0)            # Get the input again for compare
    irq(0)                         .side(0)            # Signal SampleClk interrupt 
    jmp(x_not_y, "extra")          .side(0)[4]         # Check if the input sample changed, if so, we need to add a clock
    mov(x, pins)                   .side(0)            # Get the input again
    jmp(x_not_y, "sub")            .side(0)            # Compare it to earler sample, if differnt we need to subtract a clock
    jmp("cont")                    .side(0)[1]         # No adjustment needed, so just jump back to start

    label("extra")        
    jmp("cont")                    .side(2)[2]         # Need to add a clock so delay an extra amount

    wrap()

# ------------------------------------
# Generate the TX Clock PLL at the baud rate. 
#   In Pins: n/a
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pins: tx signaal tocpu1 and tocpu2
#   Side pins: 
# ------------------------------------

@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW] * 2)
def txclock(): # clcokdiv 8125
    wrap_target()

    wait(1, irq, 4)[5]                                  # Wait for Sample Clk
    set(pins, 3)                                        # output one
    wait(1, irq, 4)[5]                                  # Wait for Sample Clk
    set(pins, 0)                                        # output zero and wait for next sample clock

    wrap()

# ------------------------------------
# Wait for Interrupt 0 from previous PIO to signal time to sample the data
#  Can run at full clock speed of the pico
#   NRZI Decode to set pins
#   set IRQ 1 when data has been written
#   In Pins: data in (1 bit)
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pings: NRZI output
#   Side pins: 
#          pin 0 = high during wait, low when running
# ------------------------------------

@rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, set_init=rp2.PIO.OUT_LOW)
def nrzi():# clock div 4 
    mov(x, null)
    jmp("waiti")

    wrap_target()

    label("start")
    nop()[2]                                        # delay three clocks for data bits to settle
    irq(1)                                          # Signal that we decoded a bit
    mov(x, y)                                       # Keep value for next compare

    label("waiti")          
    wait(1, irq, 0)         .side(1)                #  Wait for Sample Clk # wait for irq 0 from rxclock (PIO 0) 
    irq(4)                                          # signal tx sm
    mov(y, pins)            .side(0)                #  Grab the Input
    jmp(x_not_y, "diff")                            # Check if it is different from last sample

    label("same")
    set(pins, 1)                                    # Same, so output a 1
    jmp("start")                                    # Get ready for next bit

    label("diff")
    set(pins, 0)                                    # Different, so output a 0

    wrap()


#------------------------------------------
#
# PIO 1 sm
#
#-------------------------------------------


# ------------------------------------
# Wait for Interrupt Zero Unstuff,  only clock outgoing data if not bit stuffed
#   In Pins: NRZI decoded data pin
#   Out Pins: data out
#   Jmp Pin: n/a
#   Set Pins: n/a
#   Side pins: 
#          pin 0 = data clock
# ------------------------------------

@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, sideset_init=[rp2.PIO.OUT_LOW], autopush=True, push_thresh=8, out_init=rp2.PIO.OUT_LOW)
def receiveData():
    label("resetall")
    mov(isr, null)                  .side(0)       # clear isr

    wrap_target()

    label("resetX")
    set(x, 4)                       .side(0)       #  wait for 5 ones in a row

    label("next1")
    wait(1, irq, 28)                 .side(0)[7]    # Wait for flag detector to be done, wait for input to be stable
    # waits for flag deteector irq, which is in the next block = wait 1 irq next 4 
    # # 001 00000 1 10 11100 = 
    jmp(pin, "resetall")            .side(0)       # check if flag pin is set -------- have to set pin when initializing sm
    mov(y, pins)                    .side(0)       # grab the input data
    # mov(pins, y)                    .side(0)       # set the data output to the input
    in_(y, 1)                       .side(1)       # shift in data bit
    jmp(not_y, "resetX")            .side(0)       # check for a zero

    label("output1")
    jmp(x_dec, "next1")             .side(1)       # clock out the data but next bit might need to be skipped

    label("ones5")
    wait(1, irq, 28)                 .side(0)[7]    # Wait for flag detector to be done
    # waits for flag deteector irq, which is in the next block = wait 1 irq next 4 
    # # 001 00000 1 10 11100 = 
    jmp(pin, "resetall")            .side(0)       # check if flag pin is set
    mov(y, pins)                    .side(0)       # get input
    # mov(pins, y)                    .side(0)       # put on data line but not clock line
    jmp(not_y, "resetX")            .side(0)       # skip the zero by not outputting a clock
    in_(y, 1)                       .side(1)       # shift in data bit

    wrap()

#------------------------------------------
#
# PIO 2 sm
#
#-------------------------------------------
# ------------------------------------
# WS Led
#   In Pins: n/a
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pins: n/a
#   Side pins: 
#          pin 0 = led data
# ------------------------------------
@rp2.asm_pio(out_shiftdir=rp2.PIO.SHIFT_LEFT, autopull=True, pull_thresh=24, sideset_init=rp2.PIO.OUT_LOW)
def wsled():
    wrap_target()

    label("bitloop")
    out(x, 1)                   .side(0)[3]                    
    jmp(not_x, "do_zero")       .side(1)[2]  

    label("do_one")
    jmp("bitloop")              .side(1)[2]          

    label("do_zero")
    nop()                       .side(0)[2]                 

    wrap()


# ------------------------------------
# Wait for Interrupt 1 from PIO 0 (next PIO relative to PIO2) to signal time to sample
#   set IRQ 3 when flag is detected
#   In Pins: NRZI decoded data pin
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pings: n/a
#   Side pins: 
#          pin 0 = high when current bit is the last bit of a valid flag char
# ------------------------------------

@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, sideset_init=[rp2.PIO.OUT_LOW]) #side set 1 opt 
def flag():     # clock div= 4 
    pull(block)                    .side(0)         # Get Flag Value from High level Code
    mov(x, osr)                    .side(0)         # Save it in X forever              

    wrap_target()
    label("waiti")

    in_(isr, 8)                                     # put isr back at high bits to prepare for shift
    irq(4)                  # MIGHT NEED nowait                        # Let unstuffer know we finished
    # wait(1, irq, 9)       # word(0x20c9)                                    # 0010000011001001 = wait 1 prev irq 1 word equivalent because upython doesnt have next or prev 
    wait (1, irq, 25 )      # 001 00000 1 10 11001 = waiting for next, so next would be PIO 0 
   
    in_(pins, 1)                                    # Grab the new bit
    in_(null, 24)                                   # move it to low byte (shift in 24 zeros)
    mov(y, isr)                                     # Grab the current shifted value
    jmp(x_not_y, "waiti")            .side(0)       # Compare to a Flag char
    irq(3)                           .side(1)       # FLAG was detected

    wrap()


# ------------------------------------
# 
#  
#  End of PIO #
#  Beginning of High-level code to 
#  set up the PIO state machines
#   
#         
# ------------------------------------
# /*
#   PIO Resources:
#   PIO 0     - python uses indexs 0 - 3 to set sm in PIO 0 
#     sm 0    Rx CLK PLL
#     sm 1    NRZI decode (not zero unstuff)
#     sm 2    Tx Clock to CPU1 and CPU2
#     sm 3
#     irq 0   Rx Sample Clock
#     irq 1   NRZI clock
#     irq 2
#     irq 3
#     irq 4   NRZI output ready for txclock
#     irq 5
#     irq 6
#     irq 7
#     IRQ 0
#     IRQ 1
  
#   PIO 1     - python uses index 4 - 7 to set sm in PIO 1 
#     sm 0    
#     sm 1    zero unstuffer, receiveData           
#     sm 2
#     sm 3
#     irq 0
#     irq 1
#     irq 2  
#     irq 3  
#     irq 4  
#     irq 5  
#     irq 6
#     irq 7
#     IRQ 0  
#     IRQ 1  SM 1 Rx Fifo not Empty

#   PIO 2
#     sm 0  wsled
#     sm 1  Flag Detector
#     sm 2
#     sm 3
#     irq 0
#     irq 1
#     irq 2 
#     irq 3 flag detected
#     irq 4 flag detector output ready for unstuff
#     irq 5
#     irq 6
#     irq 7
#     IRQ 0 flag detector
#     IRQ 1
# */

pinUARTtx       =     0
pinUARTrx       =     1
pinWSLed        =     2
pinSampleCLK    =     3
pinPLLAdd       =     4
pinPLLSub       =     5
pinNRZIdecode   =     6
pinFlag         =     7     ## Last bit received was end of a flag char 
pinClk          =     8     ## Decoded data stream clock (falling edge sample)
pinData         =     9     ##Decoded data stream (sample on falling clock edge)
pinToCPU1       =     10
pinToCPU2       =     11
pin12           =     12
pin13           =     13
pinFromCPU      =     14
pin15           =     15
pin16           =     16
pin17           =     17
pin18           =     18
pin19           =     19
pin20           =     20
pin21           =     21
pinSwitch       =     22
pin26           =     26
pin27           =     27
pin28           =     28


pin_pinFromCPU    = Pin(pinFromCPU, Pin.IN, Pin.PULL_UP) 
    
pin_sample_pin    = Pin(pinSampleCLK)
pin_nrzi_pin      = Pin(pinNRZIdecode)
pin_cpu1_pin      = Pin(pinToCPU1, Pin.OUT)
pin_cpu2_pin      = Pin(pinToCPU2, Pin.OUT)
pin_pinFlag       = Pin(pinFlag)
pin_pinClk        = Pin(pinClk)
pin_pinData       = Pin(pinData)
#-------------------------------------------------------
#       WS LED
#-------------------------------------------------------

# /*
#   LED API
#   31-24  Effect  bits
#   23-16  Green
#   15-8   Red
#   7-0    Blue

#     Effect Bits:
#     7 6 5 4   3 2 1 0
#               x x x x  Time +1 in deci seconds (zero is 16 cycles, 1 is one cycle thru)
#           x            Reserved
#         x              0 = Always, 1 = one time
#       x                0 = solid, 1 = blink every time cycles
#     x                  0 = on,  1 = off        
    
#   An LED Status array contains the current status of the led
#   7 6 5 4  3 2 1 0
#            x x x x  Current count down time value
#         x           1 = counting down
#   x                 0 = on, 1 = off
  
# */

# --------------------------------------------------------
# LED API AND GLOBALS
# --------------------------------------------------------
## LED STATUS
LED_NORMAL    =     0x00000000
LED_ONOFF     =     0x80000000
LED_BLINK     =     0x40000000
LED_ONETIME   =     0x20000000
LED_RESERVED  =     0x10000000
LED_COUNTDOWN =     0x10000000
LED_TIMEMASK  =     0x0F000000

#LeD TIME
LED_0_1sec  =  0x01000000
LED_0_2sec  =  0x02000000
LED_0_3sec  =  0x03000000
LED_0_4sec  =  0x04000000
LED_0_5sec  =  0x05000000
LED_1_0sec  =  0x0A000000
LED_1_5sec  =  0x0F000000
LED_1_6sec  =  0x00000000
LED_FAST    =  0x01000000

Brightness = 0.1

def urgb_u32(effect, r, g, b):

    red = int(r * Brightness)
    green = int(g * Brightness)
    blue = int(b * Brightness)
    return ((effect & 0xFF) << 24) | (red << 8) | (green << 16) | blue

LEDOFF = urgb_u32(LED_NORMAL, 0x00,0x00,0x00)
LEDRED  = urgb_u32(LED_NORMAL, 0xFF,0x00,0x00)
LEDGREEN = urgb_u32(LED_NORMAL, 0x00,0xFF,0x00)
LEDBLUE = urgb_u32(LED_NORMAL, 0x00,0x00,0xFF)
LEDCYAN = urgb_u32(LED_NORMAL, 0x00,0xFF,0xFF)
LEDYELLOW = urgb_u32(LED_NORMAL, 0xFF,0xFF,0x00)
LEDMAGENTA = urgb_u32(LED_NORMAL, 0xFF,0x00,0xFF)
LEDWHITE = urgb_u32(LED_NORMAL, 0xFF,0xFF,0xFF)

NUMLEDS = 3
leds      = [0, 0, 0]
ledStatus = [0, 0, 0]

sLock = _thread.allocate_lock() # semaphore lock 

sm_wsled = None

def Led_Service():
    global leds, ledStatus
    while True:
        with sLock:
            for i in range(NUMLEDS): 
                led = leds[i]
                if led & LED_ONOFF:
                    ledStatus[i] = LEDOFF
                elif led & (LED_BLINK | LED_ONETIME):
                    if not (ledStatus[i] & LED_COUNTDOWN):
                        ledStatus[i] = led | LED_COUNTDOWN
                    else:
                        cntDown = ((ledStatus[i] & LED_TIMEMASK) >> 24) - 1
                        if cntDown == 0:
                            if led & LED_ONETIME: 
                                leds[i] &= LED_ONOFF
                                ledStatus[i] = LEDOFF
                            if led & LED_BLINK:
                                if ledStatus[i] & LED_ONOFF:
                                    ledStatus[i] = led 
                                else: 
                                    ledStatus[i] = LEDOFF | LED_ONOFF | LED_COUNTDOWN | (led & LED_TIMEMASK)
                        else:
                            cntDown = (ledStatus[i] & LED_TIMEMASK) >> 24
                            cntDown -= 1
                            ledStatus[i] &= ~LED_TIMEMASK
                            ledStatus[i] |= (cntDown << 24)
                else:
                    ledStatus[i] = led

            for j in range(NUMLEDS):
                put_pixel(ledStatus[j])
            
        sleep_ms(100)
            

def put_pixel(pixel_grb):

    global sm_wsled
    sm_wsled.put((pixel_grb << 8) & 0xFFFFFFFF)

# --------------------------------------------------------
# PIOS
# --------------------------------------------------------

flagcount = 0
datacount = 0
pio1unknownIRQ0 = 0
packetlen = 0
packet = bytearray(1024)

leds = [LEDOFF, LEDOFF, LEDOFF] 
# globals
PIO0_ADDRESS = 0x50200000               # base address of PIO0
PIO1_ADDRESS       = 0x50300000         # address for PIO1 
PIO2_ADDRESS = 0x50400000
PIO_IRQ_OFFSET  = 0x030                 # regular irq offset
PIO_IRQ_INTE = 0x168                    # irq enable

# Page 84 - Interrupts
# PIO0_IRQ_0 = 15                        
# PIO0_IRQ_1 = 16
PIO1_IRQ_0 = 17
# PIO1_IRQ_1 = 18
PIO2_IRQ_0 = 19
# PIO2_IRQ_1 = 20

PIO_HARD_IRQ0 = 0x170                   # IRQ0_INTE (Interrupt Enable for irq0)
PIO_HARD_IRQ1 = 0x17c                   # IRQ1_INTE (Interrupt Enable for irq1)
NVIC_ISER0 = 0xE000E100                 # NVIC ISER0 
NVIC_ISER1 = 0x0e104
FSTAT = 0x004           # page 947


# --------------------------------------------------------
# Data IRQ handler      (PIO1)
# --------------------------------------------------------
def pio_irq_data(sm):
    global datacount, packetlen, packet
    # byte = sm.rx_fifo()

    while sm.rx_fifo() > 0:                                     # while (!pio_sm_is_rx_fifo_empty(pio, sm_data))
    # for _ in range(byte):
        data = sm.get()
        if packetlen < 1024:
            # packet[packetlen] = (data >> 24) & 0xFF             # packet[packetlen++] = data >> 24;
            packet[packetlen] = data & 0xFF
            packetlen += 1
        datacount += 1

    # mem32[PIO1_ADDRESS + PIO_HARD_IRQ1] = 0xFF     # clear irq offset MIGHT CHECK; this is 
    
# --------------------------------------------------------
# FLAG IRQ handler      (PIO2)
# --------------------------------------------------------

# def pio_irq_flag(sm):   # note this is for pio block 2 now 
#     global flagcount, pio1unknownIRQ0, packetlen, leds
    
#     # pio_interrupt = mem32[PIO2_ADDRESS + PIO_IRQ_OFFSET]    # get irq
#     pio_interrupt = sm.irq().flags() 

#     if pio_interrupt & (1 << 3):       
#         flagcount += 1   
#         # clear the irq
#         # mem32[PIO2_ADDRESS + PIO_IRQ_OFFSET] = (1 << 3)  # should auto-clear? 
#         # removed the print statements because the slock doesnt like print statements 
#         with sLock:
#             if packetlen > 2:
#                 leds[2] = LEDGREEN | LED_ONETIME | LED_FAST
#             else:
#                 leds[2] = LEDRED | LED_ONETIME | LED_0_5sec
           
#             # print(f"Packet len={packetlen}: ", end="")
#             for i in range(packetlen):
#                 print("{:02X} ".format(packet[i]), end="")
#             # if packetlen > 0:  # Only process if we have data
#             cmd = packet[0]
#             if cmd == 0x27:
#                 leds[1] = LEDMAGENTA
#             elif cmd == 0x9A:
#                 leds[1] = urgb_u32(0xFF, 0x00, 0x00)  # Red
#             else:
#                 leds[1] = LEDYELLOW | LED_BLINK | LED_FAST
            
#             print()  # newline

#         packetlen = 0  # Reset


#     else:
#         pio1unknownIRQ0 += 1
    
import micropython

# Enable emergency exception buffer for IRQ debugging
micropython.alloc_emergency_exception_buf(100)

# --------------------------------------------------------
# Scheduled task to handle packet processing (runs in main context)
# --------------------------------------------------------
def process_packet(dummy):
    # """Called via schedule() from IRQ - handles LED and printing"""
    global packetlen, packet, leds
   
    with sLock:
        if packetlen > 2:
            leds[2] = LEDGREEN | LED_ONETIME | LED_FAST
        else:
            leds[2] = LEDRED | LED_ONETIME | LED_0_5sec

        if packetlen > 0:
            cmd = packet[0]
            if cmd == 0x27:
                leds[1] = LEDMAGENTA
            elif cmd == 0x9A:
                leds[1] = urgb_u32(0xFF, 0x00, 0x00)  # Red
            else:
                leds[1] = LEDYELLOW | LED_BLINK | LED_FAST

    # Print packet (outside lock to avoid blocking)
    if packetlen > 0:
        print(f"Packet len={packetlen}: ", end="")
        for i in range(packetlen):
            print("{:02X} ".format(packet[i]), end="")
        print()

# --------------------------------------------------------
# FLAG IRQ handler (PIO2) - MINIMAL, FAST
# --------------------------------------------------------
packet_copy = bytearray(1024)  # Separate buffer for IRQ

def pio_irq_flag(sm):
    global flagcount, pio1unknownIRQ0, packetlen, packet, packet_copy
   
    pio_interrupt = sm.irq().flags()
   
    if pio_interrupt & (1 << 3):      
        flagcount += 1
       
        # Make a quick copy of the packet for processing
        # (Can't do complex operations in IRQ context)
        for i in range(packetlen):
            packet_copy[i] = packet[i]
       
        # Schedule the actual processing for main thread
        micropython.schedule(process_packet, None)
       
        # Reset packet length AFTER copying
        packetlen = 0
    else:
        pio1unknownIRQ0 += 1

# -----------------------------------------------------
# PIO 0 Setup for RX Clock and NRZI (and TX clock)
# -----------------------------------------------------

def setupPIO0():
    pin_pinPLLAdd     = Pin(pinPLLAdd, Pin.OUT)
    pin_pll_sub_pin   = Pin(pinPLLSub, Pin.OUT)   

    #intialize the state machines
    sm_rxclock = rp2.StateMachine(
        0, 
        rxclock, 
        freq=307200, # 156 MHz / div = 8125
        in_base=pin_pinFromCPU, 
        sideset_base=pin_pinPLLAdd
    )

    sm_nrzi = rp2.StateMachine(
        1, 
        nrzi, 
        freq=39000000, 
        in_base=pin_pinFromCPU, 
        sideset_base=pin_sample_pin, 
        set_base=pin_nrzi_pin
    )

    sm_txclock = rp2.StateMachine(
        2, 
        txclock, 
        freq=19200,         # 156 MHz / div = 8125
        set_base=pin_cpu1_pin
    )


    sm_rxclock.active(1)
    sm_nrzi.active(1)
    sm_txclock.active(1)

    print("<setupPIO0> End")


#fuqahh debugging functions (ty claude)
def quick_pin14_check():

    test_pin = Pin(pinFromCPU, Pin.IN, Pin.PULL_UP)
    samples = []
    edges = 0

    sample_rate_hz = 19200  # matches the PIO RX/TX clock setup
    sample_count = 1000
    sample_period_us = int(1000000 / sample_rate_hz)

    print(f"Sampling pin {pinFromCPU} at {sample_rate_hz} Hz...")

    next_sample_time = ticks_us()

    # Sample at the expected bit timing rather than using a fixed delay
    for _ in range(sample_count):
        while ticks_diff(ticks_us(), next_sample_time) < 0:
            pass

        curr = test_pin.value()
        samples.append(curr)
        if len(samples) > 1 and curr != samples[-2]:
            edges += 1

        next_sample_time += sample_period_us
   
    # Print summary first
    print(f"\nCollected {len(samples)} samples")
   
    if edges > 0:
        print(f"ACTIVE ({edges} edges detected)")
    else:
        print(f"NO ACTIVITY (stuck at {'HIGH' if samples[0] else 'LOW'})")
   
    # Print statistics
    ones = samples.count(1)
    zeros = samples.count(0)
    print(f"High (1): {ones} ({100*ones/len(samples):.1f}%)")
    print(f"Low (0): {zeros} ({100*zeros/len(samples):.1f}%)")
   
    # Print all bits in groups of 80 per line
    print("\n" + "="*60)
    print("BIT CAPTURE:")
    print("="*60)
   
    bits_per_line = 80
    for i in range(0, len(samples), bits_per_line):
        # Print line number
        print(f"{i:6d}: ", end="")
       
        # Print 80 bits
        line = samples[i:i+bits_per_line]
        print(''.join(str(b) for b in line))
       
        # Pause every 20 lines so you can see the output
        if (i // bits_per_line + 1) % 20 == 0:
            print(f"--- {i + bits_per_line} samples shown, pausing ---")
            sleep_ms(100)
   
    print("="*60)
    print("END OF CAPTURE\n")
   
    return edges > 0
def check_nrzi_output():
    # """Check if NRZI decoder (pin 6) is toggling"""
    test_pin = Pin(pinNRZIdecode, Pin.IN)
    samples = []
   
    for _ in range(100):
        samples.append(test_pin.value())
        sleep_ms(1)
   
    ones = samples.count(1)
    zeros = samples.count(0)
    print(f"NRZI Pin {pinNRZIdecode} samples: {ones} highs, {zeros} lows")
   
    if ones > 0 and zeros > 0:
        print("NRZI output is toggling")
    else:
        print(f"NRZI output stuck at {samples[0]}")
   
    return ones > 0 and zeros > 0
def check_rxclock_irq():
    # """Check if rxclock is generating IRQ 0"""
    # Read PIO0 IRQ status register
    pio0_irq = mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET]
    print(f"PIO0 IRQ status before clear: {pio0_irq:08X}")
   
    sleep_ms(10)
   
    pio0_irq = mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET]
    print(f"PIO0 IRQ status after 10ms: {pio0_irq:08X}")
   
    if pio0_irq & (1 << 0):
        print("rxclock is generating IRQ 0")
    else:
        print("rxclock is NOT generating IRQ 0")
def check_sm_status():
    # """Check if state machines are running and where they are"""
    SM_EXECCTRL_OFFSET = 0x0CC  # SM0 EXECCTRL
    CTRL_OFFSET = 0x000
   
    # Check if SMs are enabled
    ctrl = mem32[PIO0_ADDRESS + CTRL_OFFSET]
    print(f"PIO0 CTRL: {ctrl:08X}")
    print(f"  SM0 enabled: {bool(ctrl & (1 << 0))}")
    print(f"  SM1 enabled: {bool(ctrl & (1 << 1))}")
    print(f"  SM2 enabled: {bool(ctrl & (1 << 2))}")
   
    # Check SM0 (rxclock) execution
    sm0_execctrl = mem32[PIO0_ADDRESS + SM_EXECCTRL_OFFSET]
    print(f"SM0 EXECCTRL: {sm0_execctrl:08X}")
   
    # Check IRQ register directly
    irq_reg = mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET]
    print(f"PIO0 IRQ: {irq_reg:08X} (bit 0={bool(irq_reg & 1)}, bit 1={bool(irq_reg & 2)})")
   
    # Try manually clearing and re-reading
    mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET] = 0xFF  # Clear all IRQs
    sleep_ms(1)
    irq_reg = mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET]
    print(f"PIO0 IRQ after clear and 1ms: {irq_reg:08X}")
def check_rxclock_running():
    # """Check if rxclock sideset pins are toggling"""
    pll_add_pin = Pin(pinPLLAdd, Pin.IN)
    pll_sub_pin = Pin(pinPLLSub, Pin.IN)
   
    samples_add = []
    samples_sub = []
   
    for _ in range(50):
        samples_add.append(pll_add_pin.value())
        samples_sub.append(pll_sub_pin.value())
        sleep_ms(1)
   
    add_changes = sum(1 for i in range(1, len(samples_add)) if samples_add[i] != samples_add[i-1])
    sub_changes = sum(1 for i in range(1, len(samples_sub)) if samples_sub[i] != samples_sub[i-1])
   
    print(f"PLL Add pin (GPIO {pinPLLAdd}): {add_changes} transitions")
    print(f"PLL Sub pin (GPIO {pinPLLSub}): {sub_changes} transitions")
   
    if add_changes == 0 and sub_changes == 0:
        print("rxclock NOT executing (no sideset activity)")
        return False
    else:
        print("rxclock IS executing")
        return True
def check_rp2350_pio():
    # """Check RP2350-specific PIO configuration"""
    import machine
   
    print(f"Machine: {machine.unique_id().hex()}")
    print(f"Frequency: {machine.freq()}")
   
    # RP2350 has 3 PIO blocks (PIO0, PIO1, PIO2) vs RP2040's 2
    # Check if PIO blocks are powered/clocked
   
    # RESETS register (different on RP2350)
    RESETS_BASE = 0x40020000
    RESET_OFFSET = 0x0
    RESET_DONE_OFFSET = 0x8
   
    resets = mem32[RESETS_BASE + RESET_OFFSET]
    resets_done = mem32[RESETS_BASE + RESET_DONE_OFFSET]
   
    print(f"RESETS: {resets:08X}")
    print(f"RESET_DONE: {resets_done:08X}")
   
    # Check PIO clocks (bits 13-11 on RP2350)
    print(f"  PIO0 reset: {bool(resets & (1 << 11))}")
    print(f"  PIO1 reset: {bool(resets & (1 << 12))}")
    print(f"  PIO2 reset: {bool(resets & (1 << 13))}")
def check_sm0_stall():
    # """Check if SM0 is stalled - RP2350 version"""
    # RP2350 PIO registers (verify with RP2350 datasheet)
    # State Machine 0 register offsets from PIO base
    SM0_CLKDIV = 0x0C8      # Clock divider
    SM0_EXECCTRL = 0x0CC    # Execution control
    SM0_SHIFTCTRL = 0x0D0   # Shift control
    SM0_ADDR = 0x0D4        # Program counter
    SM0_INSTR = 0x0D8       # Current instruction
    SM0_PINCTRL = 0x0DC     # Pin control
   
    CTRL = 0x000            # PIO control register
    FSTAT = 0x004           # FIFO status
    FDEBUG = 0x008          # FIFO debug
    FLEVEL = 0x00C          # FIFO levels
   
    print("\n=== SM0 (rxclock) Debug Info ===")
   
    # Read all SM0 registers
    clkdiv = mem32[PIO0_ADDRESS + SM0_CLKDIV]
    execctrl = mem32[PIO0_ADDRESS + SM0_EXECCTRL]
    shiftctrl = mem32[PIO0_ADDRESS + SM0_SHIFTCTRL]
    addr = mem32[PIO0_ADDRESS + SM0_ADDR]
    instr = mem32[PIO0_ADDRESS + SM0_INSTR]
    pinctrl = mem32[PIO0_ADDRESS + SM0_PINCTRL]
   
    ctrl = mem32[PIO0_ADDRESS + CTRL]
    fstat = mem32[PIO0_ADDRESS + FSTAT]
    fdebug = mem32[PIO0_ADDRESS + FDEBUG]
   
    # Decode clock divider (16.8 fixed point)
    div_int = (clkdiv >> 16) & 0xFFFF
    div_frac = (clkdiv >> 8) & 0xFF
    actual_div = div_int + (div_frac / 256.0)
    target_freq = 156_000_000 / actual_div if actual_div > 0 else 0
   
    print(f"CLKDIV: 0x{clkdiv:08X}")
    print(f"  Integer: {div_int}, Fraction: {div_frac}/256")
    print(f"  Actual divisor: {actual_div:.3f}")
    print(f"  Target frequency: {target_freq:.1f} Hz")
   
    print(f"\nEXECCTRL: 0x{execctrl:08X}")
    print(f"  STATUS_SEL: {(execctrl >> 4) & 0xF}")
    print(f"  WRAP_BOTTOM: {(execctrl >> 7) & 0x1F}")
    print(f"  WRAP_TOP: {(execctrl >> 12) & 0x1F}")
    print(f"  SIDE_EN: {bool(execctrl & (1 << 30))}")
    print(f"  SIDE_PINDIR: {bool(execctrl & (1 << 29))}")
   
    print(f"\nSHIFTCTRL: 0x{shiftctrl:08X}")
    print(f"  AUTOPUSH: {bool(shiftctrl & (1 << 16))}")
    print(f"  AUTOPULL: {bool(shiftctrl & (1 << 17))}")
   
    print(f"\nPINCTRL: 0x{pinctrl:08X}")
    print(f"  SIDESET_BASE: {(pinctrl >> 26) & 0x1F}")
    print(f"  SIDESET_COUNT: {(pinctrl >> 29) & 0x7}")
    print(f"  IN_BASE: {(pinctrl >> 5) & 0x1F}")
   
    print(f"\nProgram Counter: 0x{addr:08X} (instruction {addr})")
    print(f"Current Instruction: 0x{instr:04X}")
   
    # Decode the current instruction (basic)
    opcode = (instr >> 13) & 0x7
    opcodes = ["JMP", "WAIT", "IN", "OUT", "PUSH", "PULL", "MOV", "IRQ"]
    print(f"  Opcode: {opcodes[opcode]} (0b{opcode:03b})")
   
    # Check FIFO status
    print(f"\nFSTAT: 0x{fstat:08X}")
    print(f"  TX FULL (SM0): {bool(fstat & (1 << 0))}")
    print(f"  RX EMPTY (SM0): {bool(fstat & (1 << 8))}")
    print(f"  TX FULL (SM1): {bool(fstat & (1 << 1))}")
    print(f"  RX EMPTY (SM1): {bool(fstat & (1 << 9))}")
   
    print(f"\nFDEBUG: 0x{fdebug:08X}")
    print(f"  TXSTALL (SM0): {bool(fdebug & (1 << 0))}")
    print(f"  RXSTALL (SM0): {bool(fdebug & (1 << 8))}")
   
    # Check if SM is actually enabled
    print(f"\nCTRL: 0x{ctrl:08X}")
    print(f"  SM0 ENABLE: {bool(ctrl & (1 << 0))}")
    print(f"  SM1 ENABLE: {bool(ctrl & (1 << 1))}")
    print(f"  SM2 ENABLE: {bool(ctrl & (1 << 2))}")
   
    # Diagnosis
    print("\n=== DIAGNOSIS ===")
    if not (ctrl & (1 << 0)):
        print("✗ SM0 is NOT ENABLED!")
    elif actual_div < 1.0:
        print("✗ Clock divider is invalid (too small)!")
    elif fdebug & (1 << 0):
        print("⚠ SM0 is TX stalled (waiting to write)")
    elif fdebug & (1 << 8):
        print("⚠ SM0 is RX stalled (waiting to read)")
    elif addr == 0 and instr == 0:
        print("✗ SM0 program counter is 0 - not loaded?")
    else:
        print("✓ SM0 appears configured correctly")
        print(f"  Stuck at instruction {addr}: 0x{instr:04X} ({opcodes[opcode]})")
def check_pio_programs():
    # """Show what programs are loaded in PIO memory"""
    print("\n=== PIO0 Instruction Memory ===")
    INSTR_MEM_BASE = 0x048  # Start of instruction memory
   
    for i in range(32):  # PIO has 32 instruction slots
        instr = mem32[PIO0_ADDRESS + INSTR_MEM_BASE + (i * 4)]
        if instr != 0:
            print(f"Addr {i:2d}: 0x{instr:04X}")
def check_pio2():
    # """Debug PIO2: SM0=wsled, SM1=flag"""
    PIO2_BASE = 0x50400000
    CTRL = 0x000
    FSTAT = 0x004
    FDEBUG = 0x008
    INSTR_MEM_BASE = 0x048

    # Per-SM register block offsets (24 bytes apart, same on RP2040/RP2350)
    SM_STRIDE = 0x18
    SM_CLKDIV = 0x0C8
    SM_EXECCTRL = 0x0CC
    SM_SHIFTCTRL = 0x0D0
    SM_ADDR = 0x0D4
    SM_INSTR = 0x0D8
    SM_PINCTRL = 0x0DC

    OPCODES = ["JMP", "WAIT", "IN", "OUT", "PUSH/PULL", "MOV", "IRQ", "SET"]

    def decode_instr(instr):
        opcode = (instr >> 13) & 0x7
        name = OPCODES[opcode]
        if opcode == 4:  # PUSH/PULL share opcode 4, bit7 distinguishes
            name = "PULL" if (instr >> 7) & 1 else "PUSH"
        return name

    def dump_sm(sm_index):
        base = PIO2_BASE + SM_CLKDIV + (sm_index * SM_STRIDE)
        clkdiv = mem32[base]
        execctrl = mem32[base + (SM_EXECCTRL - SM_CLKDIV)]
        shiftctrl = mem32[base + (SM_SHIFTCTRL - SM_CLKDIV)]
        addr = mem32[base + (SM_ADDR - SM_CLKDIV)]
        instr = mem32[base + (SM_INSTR - SM_CLKDIV)]
        pinctrl = mem32[base + (SM_PINCTRL - SM_CLKDIV)]

        div_int = (clkdiv >> 16) & 0xFFFF
        div_frac = (clkdiv >> 8) & 0xFF
        actual_div = div_int + (div_frac / 256.0)
        freq = 156_000_000 / actual_div if actual_div > 0 else 0

        # Correct PINCTRL bit layout (confirmed same on RP2040 and RP2350)
        out_base = pinctrl & 0x1F
        set_base = (pinctrl >> 5) & 0x1F
        sideset_base = (pinctrl >> 10) & 0x1F
        in_base = (pinctrl >> 15) & 0x1F
        out_count = (pinctrl >> 20) & 0x3F
        set_count = (pinctrl >> 26) & 0x7
        sideset_count = (pinctrl >> 29) & 0x7

        print(f"\n--- PIO2 SM{sm_index} ---")
        print(f"CLKDIV: 0x{clkdiv:08X}  divisor={actual_div:.3f}  freq={freq:.1f}Hz")
        print(f"EXECCTRL: 0x{execctrl:08X}  SIDE_EN={bool(execctrl & (1<<30))}  SIDE_PINDIR={bool(execctrl & (1<<29))}  JMP_PIN={(execctrl>>24)&0x1F}")
        print(f"SHIFTCTRL: 0x{shiftctrl:08X}  AUTOPULL={bool(shiftctrl & (1<<17))}  AUTOPUSH={bool(shiftctrl & (1<<16))}")
        print(f"PINCTRL: 0x{pinctrl:08X}")
        print(f"  OUT_BASE={out_base}  SET_BASE={set_base}  SIDESET_BASE={sideset_base}  IN_BASE={in_base}")
        print(f"  OUT_COUNT={out_count}  SET_COUNT={set_count}  SIDESET_COUNT={sideset_count}")
        print(f"ADDR: {addr}  INSTR: 0x{instr:04X} ({decode_instr(instr)})")
        return addr, instr

    ctrl = mem32[PIO2_BASE + CTRL]
    fstat = mem32[PIO2_BASE + FSTAT]
    fdebug = mem32[PIO2_BASE + FDEBUG]
    print("=== PIO2 Overview ===")
    print(f"CTRL: 0x{ctrl:08X}  SM0_EN={bool(ctrl & 1)}  SM1_EN={bool(ctrl & 2)}")
    print(f"FSTAT: 0x{fstat:08X}  SM0_TXFULL={bool(fstat & 1)}  SM0_RXEMPTY={bool(fstat & (1<<8))}  SM1_TXFULL={bool(fstat & 2)}  SM1_RXEMPTY={bool(fstat & (1<<9))}")
    print(f"FDEBUG: 0x{fdebug:08X}  SM0_TXSTALL={bool(fdebug & 1)}  SM0_RXSTALL={bool(fdebug & (1<<8))}  SM1_TXSTALL={bool(fdebug & 2)}  SM1_RXSTALL={bool(fdebug & (1<<9))}")

    print("\n=== PIO2 Instruction Memory ===")
    nonzero = 0
    for i in range(32):
        instr = mem32[PIO2_BASE + INSTR_MEM_BASE + (i * 4)]
        if instr != 0:
            nonzero += 1
            print(f"Addr {i:2d}: 0x{instr:04X} ({decode_instr(instr)})")
    if nonzero == 0:
        print("NOTHING LOADED — instruction memory is empty!")

    # Sample SM0 and SM1 PC twice, a few ms apart, to see if they're advancing
    print("\n=== PC advancement check ===")
    addr0_a, instr0_a = dump_sm(0)
    addr1_a, instr1_a = dump_sm(1)
    sleep_ms(5)
    addr0_b = mem32[PIO2_BASE + SM_ADDR]
    addr1_b = mem32[PIO2_BASE + SM_ADDR + SM_STRIDE]
    print(f"\nSM0 addr: {addr0_a} -> {addr0_b}  {'ADVANCING' if addr0_a != addr0_b else 'NOT ADVANCING (or looped back to same spot)'}")
    print(f"SM1 addr: {addr1_a} -> {addr1_b}  {'ADVANCING' if addr1_a != addr1_b else 'NOT ADVANCING (or looped back to same spot)'}")

def setupPIO1():
    global sm_unstuff
    sm_unstuff = rp2.StateMachine(
        5,
        receiveData,
        freq = 39000000,
        in_base = pin_nrzi_pin,
        sideset_base = pin_pinClk,
        jmp_pin = pin_pinFlag,
        out_base = pin_pinData
    )

    # IRQ handler 
    sm_unstuff.irq(handler=pio_irq_data)
    # sm_unstuff.irq(lambda p: pio_irq_data(sm_unstuff)) ## lambda p used to set hardware irqs
    mem32[PIO1_ADDRESS + PIO_HARD_IRQ1] |= (1<<1)   # bit 1 is SM1 RX FIFO NOT EMPTY

    sm_unstuff.active(1)

    
    # mem32[PIO1_ADDRESS] = 0x02  # enable state machines
   
    # mem32[NVIC_ISER0] = (1 << PIO1_IRQ_1)
    print("<setupPIO1> End")

def setupPIO2(): 
    global sm_wsled
    pin_pinWSLed = Pin(pinWSLed, Pin.OUT)

    sm_wsled = rp2.StateMachine(
        8,
        wsled,
        freq=8210526, # clock div 19, maybe round up if not working since its a decimal
        sideset_base=pin_pinWSLed
    )

    sm_flag = rp2.StateMachine(
        9,
        flag,
        freq = 39000000,
        in_base = pin_nrzi_pin,
        sideset_base = pin_pinFlag
    )

    # IRQ handler
    sm_flag.irq(handler=pio_irq_flag)
    sm_flag.put(0x0000007E)
    mem32[PIO2_ADDRESS + PIO_HARD_IRQ0] |= (1<<11)  # bit 11 is irq(3); when irq(3) = 1, the hard IRQ0 of sm 1  = 1 

    sm_flag.active(1)
    sm_wsled.active(1)

    # mem32[NVIC_ISER0] = (1 << PIO2_IRQ_0)
    print(f"SM5 RX fifo depth: {sm_unstuff.rx_fifo()}")
    print(f"PIO1 FSTAT: {mem32[PIO1_ADDRESS + FSTAT]:08X}")
    print("<setupPIO2> End")

#dobule check that that the definitions match the rp2
def main():
    global flagcount, datacount, pio1unknownIRQ0, packetlen, sm_unstuff
    machine.freq(156000000)
    uart = UART(1, baudrate=9600, bits=8, parity=None, stop=1)
    print(sys.implementation)
    print(sys.version)
    check_rp2350_pio()
    setupPIO0()
    # sleep_ms(100)
    # check_rxclock_running()
    # check_sm0_stall()
    # check_pio_programs()

    mem32[PIO0_ADDRESS + PIO_IRQ_OFFSET] = 0x01
    sleep_ms(10)
    # check_sm_status()
    
    # quick_pin14_check()
    # check_nrzi_output()
    # check_rxclock_irq()

    setupPIO1()
    setupPIO2()
    check_pio2()
    print(f"Flags detected: {flagcount}, Data bytes: {datacount}")
    with sLock:
        leds[0] = LEDBLUE | LED_BLINK | LED_0_5sec
        leds[1] = LEDOFF
        leds[2] = LEDOFF

    _thread.start_new_thread(Led_Service, ())

    while True:
       
        sleep_ms(100)



while True:     # pico runs automatically when powered
    main()
    
