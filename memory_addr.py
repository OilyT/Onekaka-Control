# memory_addr.py
"""PLC memory addresses for Modbus"""

ALARMS = {
    # Station alarms
    "LINE_TRIP": 600,
    "DC_24V_LOW_SHUTDOWN": 601,
    "STATION_DC_VOLT_LOW": 602,
    "PENSTOCK_PRESS_LOW_TRIP": 603,
    "OIL_PRESS_LOW_TRIP": 604,
    "TRANSFOERMER_UV": 605,
    "OVERCURRENT_EARTH_FAULT": 606,
    "NUETRAL_DISPLACEMENT_33KV": 607,
    "TRANSFORMER_TRIP": 608,
    "INTRUDER_ALARM": 609,
    "REMOTE_STOP": 610,
    "POWER_FAIL_MODE": 611,
    "STATION_PLC_LOW_VOLTS": 612,
    "STATION_LOW_KW": 613,
    "STATION_HIGH_PENSTOCK_PRESS": 614,
    "SPARE1": 615,
    "SPARE2": 616,
    "INTAKE_DC_LOW": 617,
    "SPARE3": 618,
    "POND_LESS_600MM": 619,
    "POND_LESS_1000MM": 620,
    "INTAKE_COMMS_FAIL": 621,
    "BYPASS_VALVES_LOCAL": 622,

    "RFS_VOLTAGE_LOW": 675,
    "WEIR_ANALOGUE_FAIL": 676,

    # Intake PLC alarms
    "SCOUR_VALVE_CLOSE_FAIL": 336,
    "SCOUR_VALVE_OPEN_FAIL": 337,
    "PG_VALVE_CLOSE_FAIL": 338,
    "SCREEN_CLEANER_POWER_FAIL_TRIP": 340,
    "SCREEN_CLEANER_HGIH_TEMP_TRIP": 341,
    "SCREEN_CLEANER_OC_TRIP": 342,
    "SCREEN_CLEANER_DP_SWITCH_FAIL": 343,
    "SCREEN_CLEANER_DP_SENSOR_FAIL": 344,
}

STATION_INFO = {
    "Pond Level (mm)": {"address": 50, "type": "register"},
    "Current Output (kW)": {"address": 33, "type": "register"},
    "Station Setpoint (kW)": {"address": 60, "type": "register"},
}
