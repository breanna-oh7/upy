# this is a translation of ao27.pio and ao27.c by Michael Wyrick
# pioasm was used to double check
from machine import UART
import _thread
from machine import Pin, mem32
import machine
import rp2
from time import sleep_ms, sleep

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
@rp2.asm_pio(sideset_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW])
def rxclock(): # clcokdiv 8125
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

# ------------------------------------
# Generate the TX Clock PLL at the baud rate. 
#   In Pins: n/a
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pins: tx signaal tocpu1 and tocpu2
#   Side pins: 
# ------------------------------------

@rp2.asm_pio()
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

@rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW)
def nrzi():# clock div 4 
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
# Wait for Interrupt 1 from previous PIO to signal time to sample
#   set IRQ 3 when flag is detected
#   In Pins: NRZI decoded data pin
#   Out Pins: n/a
#   Jmp Pin: n/a
#   Set Pings: n/a
#   Side pins: 
#          pin 0 = high when current bit is the last bit of a valid flag char
# ------------------------------------

@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, sideset_init=rp2.PIO.OUT_LOW) #side set 1 opt 
def flag():     # clock div= 4 
    pull(block)                    .side(0)         # Get Flag Value from High level Code
    mov(x, osr)                    .side(0)         # Save it in X forever              

    wrap_target()
    label("waiti")

    in_(isr, 8)                                     # put isr back at high bits to prepare for shift
    irq(4)                  # MIGHT NEED nowait                        # Let unstuffer know we finished
    word(0x20c9)                                    # 0010000011001001 = wait 1 prev irq 1 word equivalent because upython doesnt have next or prev 
    in_(pins, 1)                                    # Grab the new bit
    in_(null, 24)                                   # move it to low byte (shift in 24 zeros)
    mov(y, isr)                                     # Grab the current shifted value
    jmp(x_not_y, "waiti")            .side(0)       # Compare to a Flag char
    irq(3)                           .side(1)       # FLAG was detected

    wrap()

# ------------------------------------
# Wait for Interrupt Zero Unstuff,  only clock outgoing data if not bit stuffed
#   In Pins: NRZI decoded data pin
#   Out Pins: data out
#   Jmp Pin: n/a
#   Set Pins: n/a
#   Side pins: 
#          pin 0 = data clock
# ------------------------------------

@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, sideset_init=rp2.PIO.OUT_LOW, autopush=True, push_thresh=8, out_init=rp2.PIO.OUT_LOW)
def receiveData():
    label("resetall")
    mov(isr, null)                  .side(0)       # clear isr

    wrap_target()

    label("resetX")
    set(x, 4)                       .side(0)       #  wait for 5 ones in a row

    label("next1")
    wait(1, irq, 4)                 .side(0)[7]    # Wait for flag detector to be done, wait for input to be stable
    jmp(pin, "resetall")            .side(0)       # check if flag pin is set -------- have to set pin when initializing sm
    mov(y, pins)                    .side(0)       # grab the input data
    # mov(pins, y)                    .side(0)       # set the data output to the input
    in_(y, 1)                       .side(1)       # shift in data bit
    jmp(not_y, "resetX")            .side(0)       # check for a zero

    label("output1")
    jmp(x_dec, "next1")             .side(1)       # clock out the data but next bit might need to be skipped

    label("ones5")
    wait(1, irq, 4)                 .side(0)[7]    # Wait for flag detector to be done
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
#     sm 0    Flag Detector
#     sm 1    zero unstuffer, receiveData           
#     sm 2
#     sm 3
#     irq 0
#     irq 1
#     irq 2  flag detector output ready for unstuff
#     irq 3  flag detected
#     irq 4  
#     irq 5  
#     irq 6
#     irq 7
#     IRQ 0  flag detector
#     IRQ 1  SM 1 Rx Fifo not Empty

#   PIO 2
#     sm 0
#     sm 1
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
pin_pinPLLAdd     = Pin(pinPLLAdd, Pin.OUT)
pin_pll_sub_pin   = Pin(pinPLLSub, Pin.OUT)       
pin_sample_pin    = Pin(pinSampleCLK, Pin.OUT)
pin_nrzi_pin      = Pin(pinNRZIdecode, Pin.OUT)
pin_cpu1_pin      = Pin(pinToCPU1, Pin.OUT)
pin_cpu2_pin      = Pin(pinToCPU2, Pin.OUT)
pin_pinNRZIdecode = Pin(pinNRZIdecode, Pin.IN)
pin_pinFlag       = Pin(pinFlag, Pin.OUT)
pin_pinClk        = Pin(pinClk, Pin.OUT)
pin_pinData       = Pin(pinData, Pin.OUT)
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

NUMLEDS = 3
PIO1_BASE       = 0x50300000            # address for PIO1 
PIO_IRQ_OFFSET  = 0x030

LED_NORMAL    =     0x00000000
LED_ONOFF     =     0x80000000
LED_BLINK     =     0x40000000
LED_ONETIME   =     0x20000000
LED_RESERVED  =     0x10000000
LED_COUNTDOWN =     0x10000000
LED_TIMEMASK  =     0x0F000000


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

def urgb_u32(r, g, b):
    red = int(r * Brightness)
    green = int(g * Brightness)
    blue = int(b * Brightness)
    return (red << 8) | (green << 16) | blue

LEDOFF = urgb_u32(0x00,0x00,0x00)
LEDRED  = urgb_u32(0xFF,0x00,0x00)
LEDGREEN = urgb_u32(0x00,0xFF,0x00)
LEDBLUE = urgb_u32(0x00,0x00,0xFF)
LEDCYAN = urgb_u32(0x00,0xFF,0xFF)
LEDYELLOW = urgb_u32(0xFF,0xFF,0x00)
LEDMAGENTA = urgb_u32(0xFF,0x00,0xFF)
LEDWHITE = urgb_u32(0xFF,0xFF,0xFF)

leds = [LEDOFF] * NUMLEDS
ledStatus = [LEDOFF] * NUMLEDS

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


# def UpdateLeds():
#     global leds
#     for i in range(NUMLEDS):
#         put_pixel(leds[i])

# ------------------------------------
# 
#  
#  Flag IRQ Handler
#  
#         
# ------------------------------------

flagcount = 0
datacount = 0
pio1unknownIRQ0 = 0
packetlen = 0
packet = bytearray(1024)

leds = [LEDOFF, LEDOFF, LEDOFF] 

def pio_irq_flag(sm):
    global flagcount, pio1unknownIRQ0, packetlen, leds
    
    pio_interrupt = mem32[PIO1_BASE + PIO_IRQ_OFFSET]
    
    if pio_interrupt & (1 << 3):       
        flagcount += 1   
        mem32[PIO1_BASE + PIO_IRQ_OFFSET] = (1 << 3)
        
        if packetlen > 0:
            with sLock:     # have to lock leds bc its a shared resource
                if packetlen > 2:
                    leds[2] = LEDGREEN | LED_ONETIME | LED_FAST
                else:
                    leds[2] = LEDRED | LED_ONETIME | LED_0_5sec
                
                # REPLACED MATCH-CASE WITH IF-ELIF-ELSE
                cmd = packet[0]
                if cmd == 0x27:
                    leds[1] = LEDMAGENTA
                elif cmd == 0x9A: 
                    leds[1] = 0x00FF0000  
                else:
                    leds[1] = 0x000F0F00 | LED_BLINK | LED_FAST

            for i in range(packetlen):
                print("{:02X} ".format(packet[i]), end="")

            print() 
            
        packetlen = 0            
    else:
        pio1unknownIRQ0 += 1
    

    print("<setupFlag data> End")

# def pio_irq_flag(sm):
#     global flagcount, packetlen, leds, packet

#     flagcount += 1   
    
#     if packetlen > 0:
#         if packetlen > 2:
#             leds[2] = LEDGREEN | LED_ONETIME | LED_FAST
#         else:
#             leds[2] = LEDRED | LED_ONETIME | LED_0_5sec

#         for i in range(packetlen):
#             print("{:02X} ".format(packet[i]), end="")

#         match packet[0]:
#             case 0x27:
#                 leds[1] = LEDMAGENTA
#             case 0x9A: 
#                 leds[1] = 0x00FF0000  
#             case _:
#                 leds[1] = 0x000F0F00 | LED_BLINK | LED_FAST
        
#         print() 
        
#     packetlen = 0 

# --------------------------------------------------------
# Data IRQ handler
# --------------------------------------------------------
def pio_irq_data(sm):
    global datacount, packetlen, packet
    # byte = sm.rx_fifo()

    while sm.rx_fifo() > 0:                                     # while (!pio_sm_is_rx_fifo_empty(pio, sm_data))
    # for _ in range(byte):
        data = sm.get()
        if packetlen < 1024:
            packet[packetlen] = (data >> 24) & 0xFF             # packet[packetlen++] = data >> 24;
            packetlen += 1
        datacount += 1
    
    print("<setupPIRQ data> End")

# -----------------------------------------------------
# PIO 0 Setup for RX Clock and NRZI (and TX clock)
# -----------------------------------------------------

def setupPIO0():
    #intialize the state machines
    sm_rxclock = rp2.StateMachine(
        0, 
        rxclock, 
        freq=19200, 
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
        freq=19200, 
        set_base=pin_cpu1_pin
    )
    sm_rxclock.active(0)
    sm_nrzi.active(0)
    sm_txclock.active(0)

    ## pio_enable_sm_mask_in_sync(pio, 0x07) -> syncs the state machine clocks and starts them all at the same time 
    PIO0_ADDRESS = 0x50200000              # base address of PIO0
    # OFFSET = 0x000                      # 0x07 = 0111 = state machines 0, 1, 2 
    mem32[PIO0_ADDRESS] = 0x07    # mem32 enables the the state machines 

    print("<setupPIO0> End")


def setupPIO1():
    sm_flag = rp2.StateMachine(
        4,
        flag,
        freq = 39000000,
        in_base = pin_pinNRZIdecode,
        sideset_base = pin_pinFlag
    )
    # IRQ handler
    sm_flag.irq(handler=pio_irq_flag)

    sm_unstuff = rp2.StateMachine(
        5,
        receiveData,
        freq = 39000000,
        in_base = pin_pinNRZIdecode,
        sideset_base = pin_pinClk,
        jmp_pin = pin_pinFlag,
        out_base = pin_pinData
    )
    # IRQ handler 
    sm_unstuff.irq(handler=pio_irq_data)
    sm_flag.active(0)
    sm_unstuff.active(0)

    PIO1_ADDRESS = 0x50300000
    mem32[PIO1_ADDRESS] = 0x03  # enable state machines
    sm_flag.put(0x0000007E)
    print("<setupPIO1> End")

def setupPIO2():
    global sm_wsled
    pin_pinWSLed = Pin(pinWSLed, Pin.OUT)
    sm_wsled = rp2.StateMachine(
        8,
        wsled,
        freq=8210526, # clock div 19
        sideset_base=pin_pinWSLed
    )

    sm_wsled.active(1)

    print("<setupPIO2> End")

#dobule check that that the definitions match the rp2

def main():
    
    


    machine.freq(156000000)
    uart = UART(1, baudrate = 9600, bits = 8, parity = None, stop = 1)

    setupPIO0()
    setupPIO1()
    setupPIO2()

    with sLock:
        leds[0] = LEDBLUE | LED_BLINK | LED_0_5sec
        leds[1] = LEDOFF
        leds[2] = LEDOFF

    _thread.start_new_thread(Led_Service, ())   # running the Led_Service function in the second core

    while True:
        sleep_ms(1000)
       


main()
