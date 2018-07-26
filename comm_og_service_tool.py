#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" OGs Service Tool for Dji products.

 The script allows to trigger a few service functions of Dji drones.
"""

# Copyright (C) 2018 Mefistotelis <mefistotelis@gmail.com>
# Copyright (C) 2018 Original Gangsters <https://dji-rev.slack.com/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__version__ = "0.0.4"
__author__ = "Mefistotelis @ Original Gangsters"
__license__ = "GPL"

import os
import sys
import time
import enum
import types
import struct
import serial
import select
import binascii
import argparse
from ctypes import *

sys.path.insert(0, './')
from comm_serialtalk import (
  do_send_request, do_receive_reply,
)
from comm_mkdupc import *

def eprint(*args, **kwargs):
  print(*args, file=sys.stderr, **kwargs)

class PRODUCT_CODE(DecoratedEnum):
    A2     =  0 # Released 2013-09-04 A2 Flight Controller
    P330   =  1 # Released 2013-01-07 Phantom 1
    P330V  =  2 # Released 2013-10-28 Phantom 2 Vision
    P330Z  =  3 # Released 2013-12-15 Phantom 2 w/ Zenmuse H3-2D
    P330VP =  4 # Released 2014-04-07 Phantom 2 Vision+
    WM610  =  5 # Released 2014-11-13 Inspire 1
    P3X    =  6 # Released 2015-03-09 Phantom 3 Professional
    P3S    =  7 # Released 2015-03-09 Phantom 3 Advanced
    MAT100 =  8 # Released 2015-06-08 Matrice 100
    P3C    =  9 # Released 2015-08-04 Phantom 3 Standard
    MG1    = 10 # Released 2015-11-27 Agras MG-1
    P3XW   = 11 # Released 2016-01-05 Phantom 3 4K
    WM330  = 12 # Released 2016-03-02 Phantom 4 (now referenced as Phantom 4 Standard)
    MAT600 = 13 # Released 2016-04-17 Matrice 600
    WM220  = 14 # Released 2016-09-28 Mavic Pro (also includes Released 2017-08-24 Mavic Pro Platinum)
    WM620  = 15 # Released 2016-11-16 Inspire 2
    WM331  = 16 # Released 2016-11-16 Phantom 4 Pro
    MAT200 = 17 # Released 2017-02-26 Matrice 200
    MG1S   = 18 # Released 2017-03-28 Agras MG-1S
    WM332  = 19 # Released 2017-04-13 Phantom 4 Advanced
    WM100  = 20 # Released 2017-05-24 Spark
    WM230  = 21 # Released 2018-01-23 Mavic Air
    WM335  = 22 # Released 2018-05-08 Phantom 4 Pro V2

ALT_PRODUCT_CODE = {
    'S800': 'A2', # Released 2012-07-25 Hexacopter frame, often sold with Dji A2 Flight Controller
    'S1000': 'A2', # Released 2014-02-24 Octocopter frame, often sold with Dji A2 Flight Controller
    'S900': 'A2', # Released 2014-08-04 Hexacopter frame, often sold with Dji A2 Flight Controller
    'PH3PRO': 'P3X',
    'PH3ADV': 'P3S',
    'PH3STD': 'P3C',
    'P4': 'WM330',
    'PH4': 'WM330',
    'SPARK': 'WM100',
    'MAVIC': 'WM220',
}

class SERVICE_CMD(DecoratedEnum):
    FlycParam = 0
    GimbalCalib = 1

class FLYC_PARAM_CMD(DecoratedEnum):
    LIST = 0
    GET = 1
    SET = 2

def detect_serial_port(po):
    """ Detects the serial port device name of a Dji product.
    """
    import serial.tools.list_ports
    #TODO: detection unfinished
    for comport in serial.tools.list_ports.comports():
        print(comport.device)
    return ''

def open_serial_port(po):
    # Open serial port
    if po.port == 'auto':
        port_name = detect_serial_port(po)
    else:
        port_name = po.port
    if not po.dry_test:
        ser = serial.Serial(port_name, baudrate=po.baudrate, timeout=0)
    else:
        ser = open(os.devnull,"rb+")
        ser.port = port_name
        ser.baudrate=po.baudrate
        ser.reset_input_buffer = types.MethodType(lambda x: None, ser)
        ser.in_waiting = 0
    if (po.verbose > 0):
        print("Opened {} at {}".format(ser.port, ser.baudrate))
    return ser

def get_unique_sequence_number(po):
    """ Returns a sequence number for packet.
    """
    # This will be unique as long as we do 10ms delay between packets
    return int(time.time()*100) & 0xffff

def send_request_and_receive_reply(po, ser, receiver_type, receiver_index, ack_type, cmd_set, cmd_id, payload):
    global last_seq_num
    if not 'last_seq_num' in globals():
        last_seq_num = get_unique_sequence_number(po)

    pktprop = PacketProperties()
    pktprop.sender_type = COMM_DEV_TYPE.PC
    pktprop.sender_index = 0
    pktprop.receiver_type = receiver_type
    pktprop.receiver_index = receiver_index
    pktprop.seq_num = last_seq_num
    pktprop.pack_type = PACKET_TYPE.REQUEST
    pktprop.ack_type = ack_type
    pktprop.encrypt_type = ENCRYPT_TYPE.NO_ENC
    pktprop.cmd_set = cmd_set
    pktprop.cmd_id = cmd_id
    if hasattr(payload, '__len__'):
        pktprop.payload = (c_ubyte * len(payload)).from_buffer_copy(payload)
    else:
        pktprop.payload = (c_ubyte * sizeof(payload)).from_buffer_copy(payload)

    for nretry in range(0, 3):
        pktreq = do_send_request(po, ser, pktprop)

        pktrpl = do_receive_reply(po, ser, pktreq)

        if pktrpl is not None:
            break

    last_seq_num += 1

    if (po.verbose > 1):
        if pktrpl is not None:
            print("Received response packet:")
        else:
            print("No response received.")

    if (po.verbose > 0):
        if pktrpl is not None:
            print(' '.join('{:02x}'.format(x) for x in pktrpl))

    return pktrpl

def flyc_request_assistant_unlock(po, ser, val):
    if (po.verbose > 0):
        print("Sending Assistant Unlock request.")
    payload = DJIPayload_FlyController_AssistantUnlockRq()
    payload.lock_state = val

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xdf,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 0e 04 66 03 0a 9d a5 80 03 df 00 a7 92")

    if pktrpl is None:
        raise ConnectionError("No response on Assistant Unlock request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if rplpayload is None:
        raise ConnectionError("Unrecognized response to Assistant Unlock request.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def flyc_param_request_2017_get_table_attribs(po, ser, table_no):
    payload = DJIPayload_FlyController_GetTblAttribute2017Rq()
    payload.table_no = table_no

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xe0,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        if table_no < 2:
            pktrpl = bytes.fromhex("55 19 04 e4 03 0a 9e a5 80 03 e0 00 00 00 00 2f 87 ca 7a 86 01 00 00 55 e7")
        else:
            pktrpl = bytes.fromhex("55 0f 04 a2 03 0a a0 a5 80 03 e0 09 00 17 f4")

    if pktrpl is None:
        raise ConnectionError("No response on get table attribs request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (rplpayload is None):
        raise LookupError("Unrecognized response to get table attribs request.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def flyc_param_request_2017_get_param_info_by_index(po, ser, table_no, param_idx):
    payload = DJIPayload_FlyController_GetParamInfoByIndex2017Rq()
    payload.table_no = table_no
    payload.param_index = param_idx

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xe1,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 48 04 57 03 0a 1b 70 80 03 e1 00 00 00 00 82 00 08 00 04 00 5c 8f da 40 0a d7 23 3c 00 00 c8 42 67 5f 63 6f 6e 66 69 67 2e 6d 72 5f 63 72 61 66 74 2e 72 6f 74 6f 72 5f 36 5f 63 66 67 2e 74 68 72 75 73 74 00 8f a6")

    if pktrpl is None:
        raise ConnectionError("No response on parameter {:d} info by index request.".format(param_idx))

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    paraminfo = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (paraminfo is None):
        raise ConnectionError("Unrecognized response to parameter {:d} info by index request.".format(param_idx))

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(paraminfo).__name__))
        print(paraminfo)

    return paraminfo

def flyc_param_request_2015_get_param_info_by_index(po, ser, param_idx):
    payload = DJIPayload_FlyController_GetParamInfoByIndex2015Rq()
    payload.param_index = param_idx

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xf0,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 2e 04 a7 03 0a 77 45 80 03 f0 00 0a 00 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 67 6c 6f 62 61 6c 2e 73 74 61 74 75 73 00 79 ac")

    if pktrpl is None:
        raise ConnectionError("No response on parameter {:d} info by index request.".format(param_idx))

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    paraminfo = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (paraminfo is None):
        raise ConnectionError("Unrecognized response to parameter {:d} info by index request.".format(param_idx))

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(paraminfo).__name__))
        print(paraminfo)

    return paraminfo

def flyc_param_request_2015_get_param_info_by_hash(po, ser, param_name):
    payload = DJIPayload_FlyController_GetParamInfoByHash2015Rq()
    payload.param_hash = flyc_parameter_compute_hash(po,param_name)

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xf7,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 43 04 74 03 0a ff 7c 80 03 f7 00 01 00 02 00 0b 00 14 00 00 00 f4 01 00 00 78 00 00 00 67 5f 63 6f 6e 66 69 67 2e 66 6c 79 69 6e 67 5f 6c 69 6d 69 74 2e 6d 61 78 5f 68 65 69 67 68 74 5f 30 00 5d 71")

    if pktrpl is None:
        raise ConnectionError("No response on parameter info by hash request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    paraminfo = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (paraminfo is None):
        raise LookupError("Unrecognized response to parameter info by hash request.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(paraminfo).__name__))
        print(paraminfo)

    return paraminfo

def flyc_param_request_2015_read_param_value_by_hash(po, ser, param_name):
    payload = DJIPayload_FlyController_ReadParamValByHash2015Rq()
    payload.param_hash = flyc_parameter_compute_hash(po,param_name)

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xf8,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 14 04 6d 03 0a 00 7d 80 03 f8 00 8a 23 71 03 f4 01 57 ee")

    if pktrpl is None:
        raise ConnectionError("No response on read parameter value by hash request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (rplpayload is None):
        raise LookupError("Unrecognized response to read parameter value by hash request.")

    if sizeof(rplpayload) <= 4:
        raise ValueError("Response indicates parameter does not exist or has no retrievable value.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def flyc_param_request_2017_read_param_value_by_index(po, ser, table_no, param_idx):
    payload = DJIPayload_FlyController_ReadParamValByIndex2017Rq()
    payload.table_no = table_no
    payload.unknown1 = 1
    payload.param_index = param_idx

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xe2,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 15 04 a9 03 0a 5a 6c 80 03 e2 00 00 00 00 9e 00 f4 01 10 b1")

    if pktrpl is None:
        raise ConnectionError("No response on parameter {:d} info by index request.".format(param_idx))

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (rplpayload is None):
        raise ConnectionError("Unrecognized response to parameter {:d} info by index request.".format(param_idx))

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def do_assistant_unlock(po, ser):
    try:
        rplpayload = flyc_request_assistant_unlock(po, ser, 1)

        if rplpayload.status != 0:
            raise ValueError("Denial status {:d} returned from Assistant Unlock request.".format(rplpayload.status))

    except Exception as ex:
        if (po.verbose > 0):
            print("Error: "+str(ex))
        eprint("Assistant Unlock command failed; further commands may not work because of this.")
        return False

    return True

def flyc_param_request_2017_write_param_value_by_index(po, ser, table_no, param_idx, param_val):
    if len(param_val) > 16:
        payload = DJIPayload_FlyController_WriteParamValAnyByIndex2017Rq()
    elif len(param_val) > 8:
        payload = DJIPayload_FlyController_WriteParamVal16ByIndex2017Rq()
    elif len(param_val) > 4:
        payload = DJIPayload_FlyController_WriteParamVal8ByIndex2017Rq()
    elif len(param_val) > 2:
        payload = DJIPayload_FlyController_WriteParamVal4ByIndex2017Rq()
    elif len(param_val) > 1:
        payload = DJIPayload_FlyController_WriteParamVal2ByIndex2017Rq()
    else:
        payload = DJIPayload_FlyController_WriteParamVal1ByIndex2017Rq()
    payload.table_no = table_no
    payload.unknown1 = 1
    payload.param_index = param_idx
    payload.param_value = (c_ubyte * sizeof(payload.param_value)).from_buffer_copy(param_val)

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xe3,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 15 04 a9 03 0a 1a de 80 03 e3 00 00 00 00 9e 00 f3 01 a7 40")

    if pktrpl is None:
        raise ConnectionError("No response on write parameter value by index request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (rplpayload is None):
        raise LookupError("Unrecognized response to write parameter value by index request.")

    if sizeof(rplpayload) <= 4:
        raise ValueError("Response indicates parameter does not exist or is not writeable.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def flyc_param_request_2015_write_param_value_by_hash(po, ser, param_name, param_val):
    if len(param_val) > 16:
        payload = DJIPayload_FlyController_WriteParamValAnyByHash2015Rq()
    elif len(param_val) > 8:
        payload = DJIPayload_FlyController_WriteParamVal16ByHash2015Rq()
    elif len(param_val) > 4:
        payload = DJIPayload_FlyController_WriteParamVal8ByHash2015Rq()
    elif len(param_val) > 2:
        payload = DJIPayload_FlyController_WriteParamVal4ByHash2015Rq()
    elif len(param_val) > 1:
        payload = DJIPayload_FlyController_WriteParamVal2ByHash2015Rq()
    else:
        payload = DJIPayload_FlyController_WriteParamVal1ByHash2015Rq()
    payload.param_hash = flyc_parameter_compute_hash(po,param_name)
    payload.param_value = (c_ubyte * sizeof(payload.param_value)).from_buffer_copy(param_val)

    if (po.verbose > 2):
        print("Prepared request - {:s}:".format(type(payload).__name__))
        print(payload)

    pktrpl = send_request_and_receive_reply(po, ser,
      COMM_DEV_TYPE.FLYCONTROLLER, 0,
      ACK_TYPE.ACK_AFTER_EXEC,
      CMD_SET_TYPE.FLYCONTROLLER, 0xf9,
      payload)

    if po.dry_test:
        # use to test the code without a drone
        pktrpl = bytes.fromhex("55 14 04 6d 03 0a 37 c6 80 03 f9 00 8a 23 71 03 f3 01 dd dd")

    if pktrpl is None:
        raise ConnectionError("No response on write parameter value by hash request.")

    rplhdr = DJICmdV1Header.from_buffer_copy(pktrpl)
    rplpayload = get_known_payload(rplhdr, pktrpl[sizeof(DJICmdV1Header):-2])

    if (rplpayload is None):
        raise LookupError("Unrecognized response to write parameter value by hash request.")

    if sizeof(rplpayload) <= 4:
        raise ValueError("Response indicates parameter does not exist or is not writeable.")

    if (po.verbose > 2):
        print("Parsed response - {:s}:".format(type(rplpayload).__name__))
        print(rplpayload)

    return rplpayload

def flyc_param_info_limits_to_str(po, paraminfo):
    if (isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoU2015Re) or
      isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoU2017Re)):
        limit_min = '{:d}'.format(paraminfo.limit_min)
        limit_max = '{:d}'.format(paraminfo.limit_max)
        limit_def = '{:d}'.format(paraminfo.limit_def)
    elif (isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoI2015Re) or
      isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoI2017Re)):
        limit_min = '{:d}'.format(paraminfo.limit_min)
        limit_max = '{:d}'.format(paraminfo.limit_max)
        limit_def = '{:d}'.format(paraminfo.limit_def)
    elif (isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoF2015Re) or
      isinstance(paraminfo, DJIPayload_FlyController_GetParamInfoF2017Re)):
        limit_min = '{:f}'.format(paraminfo.limit_min)
        limit_max = '{:f}'.format(paraminfo.limit_max)
        limit_def = '{:f}'.format(paraminfo.limit_def)
    else:
        limit_min = "n/a"
        limit_max = "n/a"
        limit_def = "n/a"
    return (limit_min, limit_max, limit_def)

def flyc_param_value_to_str(po, paraminfo, param_value):
    if (paraminfo.type_id == DJIPayload_FlyController_ParamType.ubyte.value):
        param_bs = bytes(param_value[:1])
        value_str = "{:d}".format(struct.unpack("<B", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ushort.value):
        param_bs = bytes(param_value[:2])
        value_str = "{:d}".format(struct.unpack("<H", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ulong.value):
        param_bs = bytes(param_value[:4])
        value_str = "{:d}".format(struct.unpack("<L", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ulonglong.value):
        param_bs = bytes(param_value[:8])
        value_str = "{:d}".format(struct.unpack("<Q", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.byte.value):
        param_bs = bytes(param_value[:1])
        value_str = "{:d}".format(struct.unpack("<b", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.short.value):
        param_bs = bytes(param_value[:2])
        value_str = "{:d}".format(struct.unpack("<h", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.long.value):
        param_bs = bytes(param_value[:4])
        value_str = "{:d}".format(struct.unpack("<l", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.longlong.value):
        param_bs = bytes(param_value[:8])
        value_str = "{:d}".format(struct.unpack("<q", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.float.value):
        param_bs = bytes(param_value[:4])
        value_str = "{:f}".format(struct.unpack("<f", param_bs)[0])
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.double.value):
        param_bs = bytes(param_value[:8])
        value_str = "{:f}".format(struct.unpack("<d", param_bs)[0])
    else: # array or future type
        value_str = ' '.join('{:02x}'.format(x) for x in param_bs)
    return value_str

def flyc_param_str_to_value(po, paraminfo, value_str):
    if (paraminfo.type_id == DJIPayload_FlyController_ParamType.ubyte.value):
        param_val = struct.pack("<B", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ushort.value):
        param_val = struct.pack("<H", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ulong.value):
        param_val = struct.pack("<L", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.ulonglong.value):
        param_val = struct.pack("<Q", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.byte.value):
        param_val = struct.pack("<b", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.short.value):
        param_val = struct.pack("<h", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.long.value):
        param_val = struct.pack("<l", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.longlong.value):
        param_val = struct.pack("<q", int(value_str,0))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.float.value):
        param_val = struct.pack("<f", float(value_str))
    elif (paraminfo.type_id == DJIPayload_FlyController_ParamType.double.value):
        param_val = struct.pack("<d", float(value_str))
    else: # array or future type
        param_val = bytes.fromhex(value_str)
    return param_val

def flyc_param_request_2015_print_response(po, idx, paraminfo, rplpayload):
    if paraminfo is None:
        # Print headers
        if rplpayload is None:
            param_val = ""
        else:
            param_val = "value"
        if idx is None:
            ident_str = "hash"
        else:
            ident_str = "idx"
        if po.fmt == '2line':
            print("{:10s} {:60s}".format(ident_str, "name"))
            print("{:6s} {:4s} {:6s} {:7s} {:7s} {:7s} {:7s}".format(
              "typeId", "size", "attr", "min", "max", "deflt", param_val))
        elif po.fmt == 'tab':
            print("{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}".format(
              ident_str, "name", "typeId", "size", "attr", "min", "max", "deflt", param_val))
        elif po.fmt == 'csv':
            print("{:s};{:s};{:s};{:s};{:s};{:s};{:s};{:s};{:s}".format(
              ident_str, "name", "typeId", "size", "attr", "min", "max", "deflt", param_val))
        elif po.fmt == '1line':
            print("{:10s} {:60s} {:6s} {:4s} {:6s} {:7s} {:7s} {:7s} {:7s}".format(
              ident_str, "name", "typeId", "size", "attr", "min", "max", "deflt", param_val))
        else: # po.fmt == 'simple':
            pass
    else:
        # Print actual data
        if rplpayload is None:
            param_val = ""
        else:
            param_val = flyc_param_value_to_str(po, paraminfo, rplpayload.param_value)
        if idx is None:
            if rplpayload is not None:
                ident_str = "0x{:08x}".format(rplpayload.param_hash)
            else:
                ident_str = "n/a"
        else:
            ident_str = "{:d}".format(idx)
        # Convert limits to string before, so we can handle all types in the same way
        (limit_min, limit_max, limit_def) = flyc_param_info_limits_to_str(po, paraminfo)

        if po.fmt == '2line':
            print("{:10s} {:60s}".format(ident_str, paraminfo.name.decode("utf-8")))
            print("{:6d} {:4d} 0x{:04x} {:7s} {:7s} {:7s} {:7s}".format(
              paraminfo.type_id, paraminfo.size, paraminfo.attribute,
              limit_min, limit_max, limit_def, param_val))
        elif po.fmt == 'tab':
            print("{:s}\t{:s}\t{:d}\t{:d}\t0x{:04x}\t{:s}\t{:s}\t{:s}\t{:s}".format(
              ident_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size, paraminfo.attribute,
              limit_min, limit_max, limit_def, param_val))
        elif po.fmt == 'csv':
            print("{:s};{:s};{:d};{:d};0x{:04x};{:s};{:s};{:s};{:s}".format(
              ident_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size, paraminfo.attribute,
              limit_min, limit_max, limit_def, param_val))
        #elif po.fmt == 'json': #TODO maybe output format similar to flyc_param_infos?
        elif po.fmt == '1line':
            print("{:10s} {:60s} {:6d} {:4d} 0x{:04x} {:7s} {:7s} {:7s} {:7s}".format(
              ident_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size, paraminfo.attribute,
              limit_min, limit_max, limit_def, param_val))
        else: # po.fmt == 'simple':
            if rplpayload is None:
                print("{:s} default = {:s} range = < {:s} .. {:s} >".format(paraminfo.name.decode("utf-8"), limit_def, limit_min, limit_max))
            else:
                print("{:s} = {:s} range = < {:s} .. {:s} >".format(paraminfo.name.decode("utf-8"), param_val, limit_min, limit_max))

def flyc_param_request_2017_print_response(po, idx, paraminfo, rplpayload):
    if paraminfo is None:
        # Print headers
        if rplpayload is None:
            param_val = ""
        else:
            param_val = "value"
        if idx is None:
            ident_str = "hash"
        else:
            ident_str = "idx"
        if po.fmt == '2line':
            print("{:10s} {:5s} {:60s}".format(ident_str, "tbl:idx", "name"))
            print("{:6s} {:4s} {:7s} {:7s} {:7s} {:7s}".format(
              "typeId", "size", "min", "max", "deflt", param_val))
        elif po.fmt == 'tab':
            print("{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}\t{:s}".format(
              ident_str, "tbl:idx", "name", "typeId", "size", "min", "max", "deflt", param_val))
        elif po.fmt == 'csv':
            print("{:s};{:s};{:s};{:s};{:s};{:s};{:s};{:s};{:s}".format(
              ident_str, "tbl:idx", "name", "typeId", "size", "min", "max", "deflt", param_val))
        elif po.fmt == '1line':
            print("{:10s} {:5s} {:60s} {:6s} {:4s} {:7s} {:7s} {:7s} {:7s}".format(
              ident_str, "tbl:idx", "name", "typeId", "size", "min", "max", "deflt", param_val))
        else: # po.fmt == 'simple':
            pass
    else:
        # Print actual data
        if rplpayload is None:
            param_val = ""
        else:
            param_val = flyc_param_value_to_str(po, paraminfo, rplpayload.param_value)
        if idx is None:
            if rplpayload is None:
                ident_str = "n/a"
            elif hasattr(rplpayload, 'param_hash'):
                ident_str = "0x{:08x}".format(rplpayload.param_hash)
            else:
                ident_str = "0x{:08x}".format(flyc_parameter_compute_hash(po,paraminfo.name.decode("utf-8")))
        else:
            ident_str = "{:d}".format(idx)
        tbl_str = "{:d}:{:d}".format(paraminfo.table_no, paraminfo.param_index)

        # Convert limits to string before, so we can handle all types in the same way
        (limit_min, limit_max, limit_def) = flyc_param_info_limits_to_str(po, paraminfo)

        if po.fmt == '2line':
            print("{:10s} {:5s} {:60s}".format(ident_str, tbl_str, paraminfo.name.decode("utf-8")))
            print("{:6d} {:4d} {:7s} {:7s} {:7s} {:7s}".format(
              paraminfo.type_id, paraminfo.size,
              limit_min, limit_max, limit_def, param_val))
        elif po.fmt == 'tab':
            print("{:s}\t{:s}\t{:s}\t{:d}\t{:d}\t{:s}\t{:s}\t{:s}\t{:s}".format(
              ident_str, tbl_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size,
              limit_min, limit_max, limit_def, param_val))
        elif po.fmt == 'csv':
            print("{:s};{:s};{:s};{:d};{:d};{:s};{:s};{:s};{:s}".format(
              ident_str, tbl_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size,
              limit_min, limit_max, limit_def, param_val))
        #elif po.fmt == 'json': #TODO maybe output format similar to flyc_param_infos?
        elif po.fmt == '1line':
            print("{:10s} {:5s} {:60s} {:6d} {:4d} {:7s} {:7s} {:7s} {:7s}".format(
              ident_str, tbl_str, paraminfo.name.decode("utf-8"),
              paraminfo.type_id, paraminfo.size,
              limit_min, limit_max, limit_def, param_val))
        else: # po.fmt == 'simple':
            if rplpayload is None:
                print("{:s} default = {:s} range = < {:s} .. {:s} >".format(paraminfo.name.decode("utf-8"), limit_def, limit_min, limit_max))
            else:
                print("{:s} = {:s} range = < {:s} .. {:s} >".format(paraminfo.name.decode("utf-8"), param_val, limit_min, limit_max))

def do_flyc_param_request_2015_list(po, ser):
    """ List flyc parameters on platforms with single, linear parameters table.

        Tested on the following platforms and FW versions:
        P3X_FW_V01.07.0060 (2018-07-22)
    """
    # Print result data header
    flyc_param_request_2015_print_response(po, True, None, None)

    for idx in range(po.start, po.start+po.count):
        rplpayload = flyc_param_request_2015_get_param_info_by_index(po, ser, idx)

        if sizeof(rplpayload) <= 4:
            if (po.verbose > 0):
                print("Response on parameter {:d} indicates end of list.".format(idx))
            break
        # Print the result data
        flyc_param_request_2015_print_response(po, idx, rplpayload, None)

def do_flyc_param_request_2015_get(po, ser):
    """ Get flyc parameter value on platforms with single, linear parameters table.

        Tested on the following platforms and FW versions:
        P3X_FW_V01.07.0060 (2018-07-22)
    """
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2015_get_param_info_by_hash(po, ser, po.param_name)
    # Now get the parameter value
    rplpayload = flyc_param_request_2015_read_param_value_by_hash(po, ser, po.param_name)
    # Print the result data
    flyc_param_request_2015_print_response(po, None, None, True)
    flyc_param_request_2015_print_response(po, None, paraminfo, rplpayload)

def do_flyc_param_request_2015_set(po, ser):
    """ Set new value of flyc parameter on platforms with single, linear parameters table.

        Tested on the following platforms and FW versions:
        P3X_FW_V01.07.0060 (2018-07-22)
    """
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2015_get_param_info_by_hash(po, ser, po.param_name)
    # Now set the parameter value
    param_val = flyc_param_str_to_value(po, paraminfo, po.param_value)
    rplpayload = flyc_param_request_2015_write_param_value_by_hash(po, ser, po.param_name, param_val)
    # Print the result data
    flyc_param_request_2015_print_response(po, None, None, True)
    flyc_param_request_2015_print_response(po, None, paraminfo, rplpayload)

def do_flyc_param_request_2017_list(po, ser):
    """ List flyc parameters on platforms multiple parameter tables.

        Tested on the following platforms and FW versions:
        WM100_FW_V01.00.0900 (2018-07-23)
    """
    do_assistant_unlock(po, ser)
    # Get info on tables first, so we can flatten them
    table_attribs = []
    for table_no in range(0, 255):
        tab_attr = flyc_param_request_2017_get_table_attribs(po, ser, table_no)
        if sizeof(tab_attr) <= 2:
            if (po.verbose > 0):
                print("Response on table no {:d} indicates end of list.".format(table_no))
            break
        table_attribs.append(tab_attr)
    # Print result data header
    flyc_param_request_2017_print_response(po, True, None, None)
    idx = 0
    for tab_attr in table_attribs:
        for tbl_idx in range(0, tab_attr.entries_num):
            if idx > po.start+po.count:
                break
            if idx >= po.start:
                rplpayload = flyc_param_request_2017_get_param_info_by_index(po, ser, tab_attr.table_no, tbl_idx)
                if sizeof(rplpayload) <= 4:
                    eprint("Response on parameter {:d} indicates end of list despite larger size reported.".format(idx))
                    # do not break - this may be error with one specific parameter
                else:
                    # Print the result data
                    flyc_param_request_2017_print_response(po, idx, rplpayload, None)
            idx += 1

def do_flyc_param_request_2017_get(po, ser):
    """ Get flyc parameter value on platforms multiple parameter tables.

        Tested on the following platforms and FW versions:
        WM100_FW_V01.00.0900 (2018-07-23)
    """
    do_assistant_unlock(po, ser)
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2015_get_param_info_by_hash(po, ser, po.param_name)
    # Now get the parameter value
    rplpayload = flyc_param_request_2015_read_param_value_by_hash(po, ser, po.param_name)
    # Print the result data
    flyc_param_request_2015_print_response(po, None, None, True)
    flyc_param_request_2015_print_response(po, None, paraminfo, rplpayload)

def flyc_param_request_2017_get_param_info_by_name_search(po, ser, param_name):
    # Get info on tables first, so we can flatten them
    table_attribs = []
    for table_no in range(0, 255):
        tab_attr = flyc_param_request_2017_get_table_attribs(po, ser, table_no)
        if sizeof(tab_attr) <= 2:
            if (po.verbose > 0):
                print("Response on table no {:d} indicates end of list.".format(table_no))
            break
        table_attribs.append(tab_attr)
    # Now find table location of our param
    idx = 0
    for tab_attr in table_attribs:
        for tbl_idx in range(0, tab_attr.entries_num):
            rplpayload = flyc_param_request_2017_get_param_info_by_index(po, ser, tab_attr.table_no, tbl_idx)
            if sizeof(rplpayload) <= 4:
                eprint("Response on parameter {:d} indicates end of list despite larger size reported.".format(idx))
                # do not break - this may be error with one specific parameter
            elif rplpayload.name.decode("utf-8") == param_name:
                return rplpayload
            idx += 1
    raise LookupError("Parameter not found during parameter info by name search request.")
    return None # unreachble

def do_flyc_param_request_2017_get_alt(po, ser):
    """ Get flyc parameter value on platforms multiple parameter tables, alternative way.

        Tested on the following platforms and FW versions:
        WM100_FW_V01.00.0900 (2018-07-26)
    """
    do_assistant_unlock(po, ser)
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2017_get_param_info_by_name_search(po, ser, po.param_name)
    # Now get the parameter value
    rplpayload = flyc_param_request_2017_read_param_value_by_index(po, ser, paraminfo.table_no, paraminfo.param_index)
    # Print the result data
    flyc_param_request_2017_print_response(po, None, None, True)
    flyc_param_request_2017_print_response(po, None, paraminfo, rplpayload)

def do_flyc_param_request_2017_set(po, ser):
    """ Set new value of flyc parameter on platforms multiple parameter tables.

        Tested on the following platforms and FW versions:
        WM100_FW_V01.00.0900 (2018-07-23)
    """
    do_assistant_unlock(po, ser)
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2015_get_param_info_by_hash(po, ser, po.param_name)
    # Now set the parameter value
    param_val = flyc_param_str_to_value(po, paraminfo, po.param_value)
    rplpayload = flyc_param_request_2015_write_param_value_by_hash(po, ser, po.param_name, param_val)
    # Print the result data
    flyc_param_request_2015_print_response(po, None, None, True)
    flyc_param_request_2015_print_response(po, None, paraminfo, rplpayload)

def do_flyc_param_request_2017_set_alt(po, ser):
    """ Set new value of flyc parameter on platforms multiple parameter tables, alternative way.

        Tested on the following platforms and FW versions:
        NONE
    """
    do_assistant_unlock(po, ser)
    # Get param info first, so we know type and size
    paraminfo = flyc_param_request_2017_get_param_info_by_name_search(po, ser, po.param_name)
    # Now set the parameter value
    param_val = flyc_param_str_to_value(po, paraminfo, po.param_value)
    rplpayload = flyc_param_request_2017_write_param_value_by_index(po, ser, paraminfo.table_no, paraminfo.param_index, param_val)
    # Print the result data
    flyc_param_request_2017_print_response(po, None, None, True)
    flyc_param_request_2017_print_response(po, None, paraminfo, rplpayload)

def do_flyc_param_request(po):
    ser = open_serial_port(po)

    if po.product.value >= PRODUCT_CODE.WM330.value:
        if po.subcmd == FLYC_PARAM_CMD.LIST:
            do_flyc_param_request_2017_list(po, ser)
        elif po.subcmd == FLYC_PARAM_CMD.GET:
            if not po.alt:
                do_flyc_param_request_2017_get(po, ser)
            else:
                do_flyc_param_request_2017_get_alt(po, ser)
        elif po.subcmd == FLYC_PARAM_CMD.SET:
            if not po.alt:
                do_flyc_param_request_2017_set(po, ser)
            else:
                do_flyc_param_request_2017_set_alt(po, ser)
        else:
            raise ValueError("Unrecognized {:s} command: {:s}.".format(po.svcmd.name, po.subcmd.name))
    else:
        if po.subcmd == FLYC_PARAM_CMD.LIST:
            do_flyc_param_request_2015_list(po, ser)
        elif po.subcmd == FLYC_PARAM_CMD.GET:
            do_flyc_param_request_2015_get(po, ser)
        elif po.subcmd == FLYC_PARAM_CMD.SET:
            do_flyc_param_request_2015_set(po, ser)
        else:
            raise ValueError("Unrecognized {:s} command: {:s}.".format(po.svcmd.name, po.subcmd.name))

    ser.close()

def do_gimbal_calib_request(po):
    ser = open_serial_port(po)

    eprint("Unimplemented command: {:s}.".format(po.svcmd.name))

    ser.close()


def parse_product_code(s):
    """ Parses product code string in known formats.
    """
    s = s.upper()
    if s in ALT_PRODUCT_CODE:
        s = ALT_PRODUCT_CODE[s]
    return s

def main():
    """ Main executable function.

      Its task is to parse command line options and call a function which performs serial communication.
    """
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('port', type=str,
            help="the serial port to write to and read from")

    parser.add_argument('product', metavar='product', choices=[i.name for i in PRODUCT_CODE], type=parse_product_code,
            help="target product code name; one of: {:s}".format(','.join(i.name for i in PRODUCT_CODE)))

    parser.add_argument('-b', '--baudrate', default=9600, type=int,
            help="the baudrate to use for the serial port (default is %(default)s)")

    parser.add_argument('-w', '--timeout', default=500, type=int,
            help="how long to wait for answer, in miliseconds (default is %(default)s)")

    parser.add_argument('--dry-test', action='store_true',
            help="internal testing mode; do not use real serial interface and use template answers from the drone.")

    parser.add_argument('-v', '--verbose', action='count', default=0,
            help="increases verbosity level; max level is set by -vvv")

    parser.add_argument('--version', action='version', version="%(prog)s {version} by {author}"
              .format(version=__version__,author=__author__),
            help="display version information and exit")

    subparsers = parser.add_subparsers(dest='svcmd', metavar='command',
            help="service command")

    subpar_flycpar = subparsers.add_parser('FlycParam',
            help="Flight Controller Parameters handling")

    subpar_gimbcal = subparsers.add_parser('GimbalCalib',
            help="Gimbal Calibration options")

    subpar_flycpar_subcmd = subpar_flycpar.add_subparsers(dest='subcmd',
            help="Flyc Param Command")

    subpar_flycpar_list = subpar_flycpar_subcmd.add_parser('list',
            help="list FlyC Parameters")
    subpar_flycpar_list.add_argument('-s', '--start', default=0, type=int,
            help="starting index")
    subpar_flycpar_list.add_argument('-c', '--count', default=100, type=int,
            help="amount of entries to show")
    subpar_flycpar_list.add_argument('-f', '--fmt', default='simple', type=str,
            choices=['simple', '1line', '2line', 'tab', 'csv'],
            help="output format")

    subpar_flycpar_get = subpar_flycpar_subcmd.add_parser('get',
            help="get value of FlyC Param")
    subpar_flycpar_get.add_argument('param_name', type=str,
            help="name string of the requested parameter")
    subpar_flycpar_get.add_argument('--alt', action='store_true',
            help="use alternative way; try in case the normal one does not work")
    subpar_flycpar_get.add_argument('-f', '--fmt', default='simple', type=str,
            choices=['simple', '1line', '2line', 'tab', 'csv'],
            help="output format")

    subpar_flycpar_set = subpar_flycpar_subcmd.add_parser('set',
            help="update value of FlyC Param")
    subpar_flycpar_set.add_argument('param_name', type=str,
            help="name string of the parameter")
    subpar_flycpar_set.add_argument('param_value', type=str,
            help="new value of the parameter")
    subpar_flycpar_set.add_argument('--alt', action='store_true',
            help="use alternative way; try in case the normal one does not work")
    subpar_flycpar_set.add_argument('-f', '--fmt', default='simple', type=str,
            choices=['simple', '1line', '2line', 'tab', 'csv'],
            help="output format")

    po = parser.parse_args()

    po.product = PRODUCT_CODE.from_name(po.product)
    po.svcmd = SERVICE_CMD.from_name(po.svcmd)

    if po.svcmd == SERVICE_CMD.FlycParam:
        po.subcmd = FLYC_PARAM_CMD.from_name(po.subcmd.upper())
        do_flyc_param_request(po)
    elif po.svcmd == SERVICE_CMD.GimbalCalib:
        do_gimbal_calib_request(po)

if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print("Error: "+str(ex))
        #raise