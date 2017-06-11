#include "hardware.h"
#include <math.h>
#include "Maths/Vector2D.h"
#include <Gait/GaitRunner.h>

#include "HeaderDefs.h"

#include "servoPosConsts.h"
#include "timingConsts.h"

#include "Commander.h"

#include "gait2.h"
##endif

from math import pi, sqrt, atan2
import struct

import utime
from pyb import ADC, gpio

import ax
from helpers import clamp
from init import myServoReturnLevels, myServoSpeeds, initServoLims
from commander import CommanderRx
from poses import g8Stand, g8FeetDown, g8Flop, g8Crouch
from IK import Gaits
from MotorDriver import MotorDriver


##define TURNG8 G8_ANIM_TURNLEFT
#define TURNG8 G8_ANIM_TURNSLOW

PROG_LOOP_TIME = 19500 # in microseconds

# TODO use const() in lots of places?

USE_ONE_SPEED = 0
THE_ONE_SPEED = 3
THE_TURN_SPEED = 7
MAX_WALK_SPD = 5

# bitmasks for buttons array
BUT_R1 = const(0x01) # center pan
BUT_R2 = const(0x02) # center pan and tilt
BUT_R3 = const(0x04) # panic
BUT_L4 = const(0x08) # second switch! fast pan mode
BUT_L5 = const(0x10) # laser switch
BUT_L6 = const(0x20) # fire gun
BUT_RT = const(0x40) # turn right
BUT_LT = const(0x80) # turn left

PRINT_DEBUG = False
PRINT_DEBUG_COMMANDER = False
PRINT_DEBUG_LOOP = False

# +153 is 45 deg offset for pan servo's mounting scheme.
PAN_CENTER = 511 + 153
TILT_CENTER = 511 + 95

LOADER_TIMEOUT_DURATION = 3000000 # microseconds
LOADER_SPEED_ON = 24
LOADER_SPEED_OFF = 0
ADC_LOADER_LIMIT = 10

PARAM_LASER_PIN = "PC1"
CMDR_ALIVE_CNT = 100

# Command settings/interpretation variables (ints)
#currentAnim = 0

# IRcnt = 1


class NumaMain(object):

    def __init__(self):
        from stm_uart_port import UART_Port
        from bus import Bus, BusError
        #bus = UART_Port(6, 38400)
        self.cmdrbus = UART_Port(1, 38400)
        self.axbus = Bus(UART_Port(2, 1000000), show=Bus.SHOW_PACKETS)
        #else:
        #    print("Unrecognized sysname: {0}".format(sysname))
        #    sys.exit()

        self.crx = CommanderRx()

        self.leg_ids = [11, 12, 13, 14, #servo11, servo21, servo31, servo41,
                        21, 22, 23, 24, #servo12, servo13, servo14, servo22,
                        31, 32, 33, 34, #servo23, servo24, servo32, servo33,
                        41, 42, 43, 44] #servo34, servo42, servo43, servo44]
        self.turret_ids = [51, 52] # pan, tilt
        self.all_ids = self.leg_ids + self.turret_ids

        self.servo51Min, self.servo51Max = PAN_CENTER - 4 * (52+30),  PAN_CENTER + 4 * (52+30)
        self.servo52Min, self.servo52Max = 511 - 4 * 31,              511 + 4 * 65

        self.flopCnt = 0

        self.loader_timeout_mode = 0 # 0 off, 1 on

        self.loopLengthList = [6500, 2900, 2300, 1800, 1600, 1450,
                                1000] #This last value is for turn speed?

        # directionPinNameA, directionPinNameB, pwmNumber, encoderNumber=None
        # TODO pins!
        self.gunMotor = MotorDriver("PC7", "PC4", "PC6")#, cs="PC5")
        self.ammoMotor = MotorDriver("PC8", "PC11", "PC9", cs="PC10")

        # Binary vars
        self.walk = False
        self.turn = False
        self.light = True
        self.kneeling = False
        self.panic = False

        self.gunbutton = False
        self.panicbutton = False
        self.fastturret = False
        self.pan_pos = PAN_CENTER
        self.tilt_pos = TILT_CENTER

        # Defaults?
        trav_rate_default = 25 # TODO distance covered by steps?
        self.travRate = trav_rate_default
        self.double_travRate = 2 * self.travRate

        # Various?
        self.turnTimeOffset = 0

    def main(self):
        self.app_init_hardware()
        self.app_init_software()
        oldLoopStart = 0
        while True:
            #TODO timing?
            loopStart = utime.ticks_us()
            self.app_control(loopStart)
            loopEnd = utime.ticks_us()
            if PRINT_DEBUG_LOOP:
                print("%ld" % (loopStart - oldLoopStart))
                oldLoopStart = self.loopStart
            utime.sleep_us(PROG_LOOP_TIME - utime.ticks_diff(loopEnd, loopStart))


    # Initialise the hardware
    def app_init_hardware(self):
        #initHardware()
        pass

    # Initialise the software
    # returns TICK_COUNT, usec
    # TODO this silly loop thing needs to be rewritten
    def app_init_software(self):
        print("It begins....")
        #initTrig() #TODO now in IK.py class
        self.gaits = Gaits()

        #ax12SetID(&servo1, 1)

        #Call gait for Standing
        g8Stand(self.axbus, self.leg_ids)

        myServoReturnLevels(self.axbus, all_ids=self.all_ids)
        print("ServoReturnLevelsSet!")
        initServoLims(self.axbus, self.all_ids)
        print("ServoLimsSet!")
        myServoSpeeds(self.axbus, self.leg_ids, self.turret_ids)
        print("ServoSpeedsSet!")

        #Setting mathy initial values for walking
        self.loopLength = 1800 # ms (units???)
        #self.half_loopLength = self.loopLength / 2 #redundant

        self.standing = 1 # ????
        g8Stand(self.axbus, self.leg_ids)

        return 0

    # This is the main loop
    #TICK_COUNT appControl(LOOP_COUNT loopCount, TICK_COUNT loopStart):
    def app_control(self, loopStart):

        # Stop IK and g8s from coinciding... make Numa stop in place.
        if self.walk == True:# and self.do_gait == True:
            g8Stand(self.axbus, self.leg_ids)

        # -------- Start Switch/Button-------
        # Switch/Button - see switch.
        # To test if it is pressed then
    #    if button.pressed():
    #        # Triggers gun test           #Want to run motors at 7.2V, so do PWM:
    #        act_setSpeed(&LeftGun, -70)   #NOTE: (7.2V / 12.6V) * 127 = 72.5714286
    #
    #        # pressed
    #        # We use the light variable to toggle stuff.
    #        if (light == True):
    #            LED_on(&statusLED)
    #            light = False
    #            #print("on!")
    #
    #        else:
    #            LED_off(&statusLED)
    #            light = True
    #            #print("off")

    #    #Check whether to stop firing guns
    #    if self.guns_firing and clockHasElapsed(self.guns_firing_start_time, guns_firing_duration):
    #        # guns_firing_duration = 0
    #        self.guns_firing = False
    #        self.gunMotor.direct_set_speed(0) #NOTE: (7.2 / 12.6) * 127 = 72.5714286
    #        self.guns_firing_start_time = clockGetus()
    #
    #    # To test if it is released then
    #    if SWITCH_released(&button):
    #        # released
    #        act_setSpeed(&LeftGun, 0)

        # -------- End   Switch/Button-------

        # -------- Start Dynamixel AX-12 Driver-------
        # Dump the current values for all servos on AX12_driver to print
    #    ax12DumpAll(&AX12_driver)
        # -------- End   Dynamixel AX-12 Driver-------

        #/////////////////////////////////////////

        self.bb_loader(loopStart)

        self.CmdrReadMsgs()
        self.cmdrAlive -= 1
        self.cmdrAlive = clamp(self.cmdrAlive, 0, CMDR_ALIVE_CNT)

        # Get current time in ms
        ms = (loopStart) / 1000 + self.spdChngOffset

        # We always move the turret to the position specified by the Commander.
        self.axbus.sync_write(self.turret_ids, ax.GOAL_POSITION, [struct.pack('<H', self.tilt_pos),
                                                                  struct.pack('<H', self.pan_pos)])

        # dump temperatures
        #if fastturret:
        #    ax12TempAll(UART3toAX12_driver)
        #    fastturret = False

        # TODO Test this!
        if self.panicbutton:
            self.flopCnt += 1
            if self.flopCnt >= 3:
                g8Crouch(self.axbus, self.leg_ids)
                self.panic = True
                print("Howdydoo? %d", self.flopCnt)
                self.flopCnt = 0
            else:
                # Exit crouch/panic, enable standing, and re-enable torque to 2nd servo of each leg.
                self.panic = False
                self.standing = 0

                # second servo of each leg
                self.axbus.sync_write(self.leg_ids[1::4], ax.TORQUE_ENABLE, [struct.pack('<H', 1) for _ in range(4)])

            self.panicbutton = False

            # Limit to one press toggling at a time.
            utime.sleep_ms(100)

        #FIRE THE GUNS!!!!!
        #TODO
#        if gunbutton:
#            self.guns_firing = True
#            self.gunMotor.direct_set_speed(-65)     #NOTE: (7.2 / 12.6) * 127 = 72.5714286
#            self.guns_firing_start_time = utime.ticks_us() #clockGetus()

        #We put "panic" before anything else that might move the legs.
        if self.panic:
            return 25000 #micro seconds

        # Decrement turn_loops continuously
        if self.turn_loops > 0:
            self.turn_loops -= 1

        if self.turnleft or self.turnright:
            # LED_off(&statusLED)
            #if PRINT_DEBUG: print("Turn!  %u\t%u", self.turnright, self.turnleft)

            if self.turn_loops < 1:
                self.loopLength = self.loopLengthList[THE_TURN_SPEED - 1]
                self.half_loopLength = self.loopLength / 2
                # Two parts:
                # 1) how far 'ms' is from the beginning of a turn animation
                # 2) how far from the beginning of a turn animation we want to start at
                self.turnTimeOffset = (ms % self.loopLength) - (0.2 * self.loopLength)

            self.turn = True
            self.turn_loops = 20
            turn_dir = 1
            if self.turnleft:
                turn_dir = -1 # Reverse turn dir here

            self.standing = 0

        elif self.turn_loops > 0:
            self.turn_loops = self.turn_loops # TODO wtf

        # Else, walking, possibly
        else:
            self.turnTimeOffset = 0

            # self.walkNewDirIK(0) # ???
            walkDIR = atan2(self.crx.walkh, self.crx.walkv)
            walkSPD = sqrt(self.crx.walkv * self.crx.walkv + self.crx.walkh * self.crx.walkh)
            #walkSPD = interpolate(walkSPD, 0,102, 0,6)
            walkSPD = int(0 + (6 - 0) * (walkSPD - 0) / (102 - 0)) # see above

            # Not walking, and not turning
            if walkSPD == 0 and self.turn_loops == 0:
                #g8Stand(self.axbus, self.leg_ids) # this is the end result already.
                self.walk = False
                if self.standing < 6:
                    self.standing += 1

            elif walkSPD > 0:
                # Debug info
                if PRINT_DEBUG:
                    print("walk! %f ", (walkDIR * 180.0 / pi))

                #Disable turning when walking joystick is moved.
                self.turn_loops = 0  #REDUNDANT
                #Disable standing g8
                self.standing = 0

                if walkSPD > MAX_WALK_SPD:
                    walkSPD = MAX_WALK_SPD
                elif walkSPD == 1 or walkSPD == 2:
                    walkSPD = 3

                if USE_ONE_SPEED:
                    walkSPD = THE_ONE_SPEED

                newLoopLength = self.loopLengthList[walkSPD - 1]
                if newLoopLength != self.loopLength:  # So we can check for change
                    # TODO spdChngOffset is cumulative? note speedPhaseFix both incr and decrs
                    self.spdChngOffset += self.speedPhaseFix(loopStart, self.loopLength, newLoopLength)
                    self.loopLength = newLoopLength
                    #self.spdChngOffset = spdChngOffset%loopLength
                self.walk = True
                self.walkNewDirIK(int(walkDIR * 180.0 / pi))
            #self.do_gait = False
        #////////////////////////////////////////

        self.half_loopLength = self.loopLength / 2
        # These don't change....
        #self.travRate = 30 - 10 # this was redundant
        #self.double_travRate = 2 * self.travRate

        #//////////////////////////
        # -------- Start Leg stuff-------

        #the 'now' variables are sawtooth waves (or triangle waves???).
        now2 = (ms - self.turnTimeOffset) % self.loopLength
        now3 = (ms - self.turnTimeOffset +  self.half_loopLength) % self.loopLength
        now4 = self.loopLength - (ms - self.turnTimeOffset) % self.loopLength
        now1 = self.loopLength - (ms - self.turnTimeOffset + self.half_loopLength) % self.loopLength

        # Above is where the commander input is interpretted.
        #
        # The next few blocks are where we determine what gait to use.

        # WALKING WITH IK via walkCode()
        #if 0:  #Disables walking
        if self.walk == True and self.turn_loops == 0:
            self.gaits.walkCode(self.loopLength, self.half_loopLength, self.travRate, self.double_travRate, now1, now2, now3, now4, self.ang_dir)
        #   #Do this in the middle of the calculations to give guns a better firing time accuracy
            # if self.guns_firing and clockHasElapsed(self.guns_firing_start_time, guns_firing_duration):
                # guns_firing_duration = 0
                # self.guns_firing = False
                # act_setSpeed(&LeftGun, 0) #NOTE: (7.2 / 12.6) * 127 = 72.5714286
                # self.guns_firing_start_time = utime.ticks_us() #clockGetus()

        # Turning with IK
        elif self.turn_loops > 0 and self.walk == False:
            self.gaits.turn_code(turn_dir, self.loopLength, self.half_loopLength, now1, now2, now3, now4)
            #print("%d\t%d\t%d\t%d",s12pos,s42pos, footH13,footH24)

        elif self.standing > 0 and self.standing <= 5:
            # g8Stand(self.axbus, self.leg_ids)
            g8FeetDown(self.axbus, self.leg_ids)

        elif self.turn_loops > 0 and self.walk == True:
            # g8Stand(self.axbus, self.leg_ids)
            g8FeetDown(self.axbus, self.leg_ids)

        self.turnright = False
        self.turnleft = False

        # Move all servos
        if self.walk == True or self.turn_loops > 0:
            self.axbus.sync_write(self.leg_ids, ax.GOAL_POSITION,
                    [struct.pack('<H', pos) for pos in
                               (self.gaits.s11pos, self.gaits.s21pos, self.gaits.s31pos, self.gaits.s41pos,
                                self.gaits.s12pos, self.gaits.s13pos, self.gaits.s14pos, self.gaits.s22pos,
                                self.gaits.s23pos, self.gaits.s24pos, self.gaits.s32pos, self.gaits.s33pos,
                                self.gaits.s34pos, self.gaits.s42pos, self.gaits.s43pos, self.gaits.s44pos)])

        # TODO
        #if PRINT_IR_RANGE:
        #    IRcnt += 1
        #
        #    if IRcnt >= 8:
        #
        #        distanceRead(distance)
        #        print("L")
        #        distanceDump(distance)
        #        print("\t")
        #
        #        distanceRead(distance2)
        #        print("R")
        #        distanceDump(distance2)
        #        printCRLF()
        #
        #    IRcnt = 0

#        if PRINT_DEBUG and walk == True:
#            print("")
        # elif PRINT_DEBUG_IK == True and turn == True: print("")
        #elif PRINT_DEBUG_IK == True and self.turn_loops > 0:
        #    print("")

        return PROG_LOOP_TIME #45000 #micro seconds
        #return 0
    #////////////////
    #/ End of Main Loop
    #////////////////


    #TICK_COUNT speedPhaseFix(TICK_COUNT clocktime, TICK_COUNT loopLenOld, TICK_COUNT loopLen)
    def speedPhaseFix(self, clocktime, loopLenOld, loopLen):
        # NOTE: Return value can be negative
        #print(clocktime, loopLenOld, loopLen)
        #time_ms = clocktime/1000
        return (((clocktime/1000) % loopLenOld) / loopLenOld -
            ((clocktime/1000) % loopLen) / loopLen * loopLen)


    # new_dir (was an int16_T)
    def walkNewDirIK(self, new_dir):
        # Calculate ang_dir
        # new_dir:
        if self.ang_dir == new_dir:
             return

        #if not previously walking with IK...
        #if not self.walk: #TODO Not needed?
        #    g8Stand()  #note: walk is now FALSE set walk after this.
        #    ang_dir = new_dir
        #    # NEED TO SET TIMING HERE
        # End former indent

        # If too big a change in direction, change to standing position, then start fresh
        #elif
        if (abs(new_dir - self.ang_dir) % 360) >= 20:

            g8Stand() # note: walk is now FALSE; g8Stand sets walk
            self.ang_dir = new_dir
        # else... e.g.
        else:
            self.ang_dir = new_dir
        return


    #TODO
    def CmdrReadMsgs(self):
        while True:
            byte = self.cmdrbus.read_byte()
            if byte is None: # emptied buffer
                break
            # process_byte will update crx with latest values from a complete packet; no need to do anything with it here
            if self.crx.process_byte(byte) == CommanderRx.SUCCESS:
                self.cmdrAlive = CMDR_ALIVE_CNT # reset keepalive
                pass
                #print('Walk: {:4d}h {:4d}v Look: {:4d}h {:4d}v {:08b}'.format(crx.walkh, crx.walkv, crx.lookh, crx.lookv, crx.button))

        # Update variables:
        out = ""
        buttonval = self.crx.button
        if buttonval & BUT_L6:
            self.gunbutton = True
            if PRINT_DEBUG_COMMANDER: out += "guns\t"
        else: self.gunbutton = False

        if buttonval & BUT_R3:
            self.panicbutton = True
            if PRINT_DEBUG_COMMANDER: out += "panic\t"
        else: self.panicbutton = False

        if buttonval & BUT_L4:
            self.fastturret = True
            if PRINT_DEBUG_COMMANDER: out += "fastpan\t"
        else: self.fastturret = False

        if buttonval & BUT_R2:
            self.pan_pos = PAN_CENTER
            self.tilt_pos = TILT_CENTER
            if PRINT_DEBUG_COMMANDER: out += "lookcenter\t"

        if buttonval & BUT_R1:
            self.pan_pos = PAN_CENTER
            if PRINT_DEBUG_COMMANDER: out += "lookfront\t"
        else:
            pass

        # laser
        if buttonval & BUT_L5 and self.cmdrAlive:
            gpio(PARAM_LASER_PIN, 1)
        else:
            gpio(PARAM_LASER_PIN, 0)

        dowalking = True
        if buttonval & BUT_LT:
            if PRINT_DEBUG_COMMANDER: out += "tlft\t"
            self.turnleft = True
            self.turnright = False
            dowalking = False
        elif buttonval & BUT_RT:
            if PRINT_DEBUG_COMMANDER: out += "trgt\t"
            self.turnright = True
            self.turnleft = False
            dowalking = False
        else: # Do nothing
            self.turnright = False
            self.turnleft = False
            self.turn = False

        if dowalking:
            # Default handling in original Commander.c - sets to range of -127 to 127 or so...
            # vals - 128 gives look a vlaue in the range from -128 to 127?
            #walkV = self.crx.walkv
            #walkH = self.crx.walkv
            pass

        if self.fastturret:
            pan_add = int(-self.crx.lookh / 10)
        else:
            pan_add = int(-self.crx.lookh / 17)
        tilt_add = int(-self.crx.lookv / 25)

        self.pan_pos = clamp(self.pan_pos + pan_add, self.servo51Min, self.servo51Max)
        self.tilt_pos = clamp(self.tilt_pos + tilt_add, self.servo52Min, self.servo52Max)

        if out:
            print(out)
        return


    def bb_loader(self, loopStart):
        if self.loader_timeout_mode:
            # TODO bug: wraparound in calculation of loader_timeout_end; reference loopCount
            if loopStart > self.loader_timeout_end:
                self.loader_timeout_mode = 0
        else:
            self.ammoMotor.direct_set_speed(LOADER_SPEED_ON)

        # TODO port this; how many bits is the ADC? Check the voltage limits
        # Use self.ammoMotor.cs as pin
        #if a2dConvert10bit(ADC_CH_ADC10) > ADC_LOADER_LIMIT:
        if ADC(self.ammoMotor.cs) > ADC_LOADER_LIMIT:
            self.ammoMotor.direct_set_speed(LOADER_SPEED_OFF)
            self.loader_timeout_mode = 1
            self.loader_timeout_end = loopStart + LOADER_TIMEOUT_DURATION

        # -------- Start Analogue Input-------
        # Dump out the raw value for Analogue Input
        # Dump out the mV (milli-volts) for Analogue Input
        #print("m1current: " << a2dConvert10bit(ADC_CH_ADC10) << "  m1current: " << a2dReadMv(ADC_CH_ADC10)"mV")


def main():
    x = NumaMain()
    x.app_init_software()
    input("Waiting... (press enter)")
    input("Now onwards! (press enter again)")
    x.main()

if __name__ == "__main__":
    main()
