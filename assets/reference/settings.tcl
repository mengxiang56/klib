#################################

#####----------------------------------------
##### Set liberate variables
#####----------------------------------------
### External Simulator (Spectre) settings ###
# set_var extsim_cmd_option      "+aps +spice -mt +liberate +rcopt=2"
# set_var extsim_deck_header     "simulator lang=spectre\nOpt1 options reltol=1e-4 \nsimulator lang=spice"
# set_var extsim_cmd              /eda2s/cadence/2016-17/RHELx86/MMSIM_15.10.627/bin/spectre

set_var extsim_leakage_option "accurate=1 brief=1 runlvl=6 method=gear gmindc=1e-15 gmin=1e-15 kcltest=1"
set_var extsim_option "accurate=1 brief=1 runlvl=6 autostop gmindc=1e-15 gmin=1e-15"
set_var extsim_save_passed all

### External Simulator (Hspice) settings ###
# set_var extsim_cmd "/eda2s/synopsys/hspice/O-2018.09-SP2/hspice/bin/hspice"
# set_var extsim_leakage_option "accurate=1 brief=1 runlvl=6 method=gear gmindc=1e-15 gmin=1e-15 kcltest=1"
# set_var extsim_option "accurate=1 brief=1 runlvl=6 autostop gmindc=1e-15 gmin=1e-15 macmod=2"

### SKI ###
#set_var ski_enable               1
#set_var ski_clean_mode           1  ;# run $ALTOSHOME/bin/clean_sm.sh to clean up inactive semaphores
#set_var ski_compatibility_mode   1

### Misc ###
#set_var parse_auto_define_leafcell   0 ;# disable auto leaf cell determination
#set_var tmpdir /dev/shm          ;# /dev/shm - use local RAM disk for tmp dir, /tmp - use local disk
#set_var extsim_deck_dir [file normalize "decks"]   ;# specify directory for SPICE decks and output files

### Input waveform ###
set_var predriver_waveform       2 ;# use pre-driver waveform

### Arc Generation
#set_var force_condition              4
#set_var define_arc_ignore_mode                 2          ;# consider -when and "-type power" in "define_arc -ignore"

### Capacitance ###
set_var char_mos_term_cap                      2        ;# use integration method to estimate device pin cap
#set_var min_capacitance_for_outputs            1        ;# write min_capacitance attribute for output pins
# set_var measure_cap_lower_rise                 0
# set_var measure_cap_upper_rise                 0.5
# set_var measure_cap_upper_fall                 1
# set_var measure_cap_lower_fall                 0.5

### Timing ###
#set_var conditional_expression       separate   ;# force or'd when conditions to be modeled separately
#set_var force_condition              3
#set_default_group -criteria {delay off power off} -unateness separate

### Constraint ###
set_var constraint_info                  2
#set_var constraint_search_time_abstol    1e-12	;# 1ps resolution for bisection search
#set_var constraint_output_load       min
#set_var nochange_mode                    1        ;# enable nochange_* constraint characterization
#set_var constraint_combinational 2
#set_var constraint_dependent_setuphold 2

### min_pulse_width ###
#set_var conditional_mpw            0       ;# 0=disable conditional mpw
#set_var mpw_slew mid

### Leakage ###
#set_var max_leakage_vector                 [expr 2**10]
#set_var leakage_float_internal_supply      0            ;# get worst case leakage for power switch cells when off
#set_var reset_negative_leakage_power       1            ;# convert negative leakage current to 0

### Power ###
set_var voltage_map                         1	;# create pg_pin groups, related_power_pin / related_ground_pin
set_var pin_based_power                     0	;# Monitor power based on Vdd pin only
#set_var power_multi_output_binning_mode	    1
#set_var power_subtract_leakage              4	;# use 4 for cells with exhaustive leakage states.
#set_var subtract_hidden_power               2   ;# subtract hidden power for all cells
#set_var subtract_hidden_power_use_default   2   ;# subtract hidden power for overlapping when, then default group

### Hidden Power ###
#set_var max_hidden_vector                   [expr 2**10]

#####----------------------------------------
##### Writing Output Files
#####----------------------------------------
set_var write_library_is_unbuffered            1
set_var sort_pins                              1
set_var pin_type_order {input inout output}
#set_var write_logic_function_group_at_end      0
#set_var sort_pins_under_when                   1
set_var cell_use_both_ff_latch_groups          2 ;# allow use of multiple ff,latch,state_table groups in userdata file
set_var user_data_override { power_down_function pg_pin }
set_var sdf_cond_style                         1
set_var parenthesize_not                       0 ;# use !A instead of !(A)
set_var driver_type_model_pad_check            1 ;# enable fix to disable output of driver_type pin attribute for tie cells CCR1407896
#set_var driver_cell_info	1 # enable  reporting for each cell input


