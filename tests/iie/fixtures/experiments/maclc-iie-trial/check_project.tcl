package require ::quartus::project
project_open -revision MacLC_IIe_Trial MacLC_IIe_Trial
set checked 0
set overlay_found 0
set trial_found 0
foreach kind {SYSTEMVERILOG_FILE VERILOG_FILE VHDL_FILE QIP_FILE SDC_FILE} {
    foreach_in_collection assignment [get_all_global_assignments -name $kind] {
        set path [lindex $assignment 2]
        if {![file isfile $path]} {error "Missing $kind: $path"}
        if {[string match */maclc-iie-trial/iie_status_overlay.sv $path]} {set overlay_found 1}
        if {[string match */maclc-iie-trial/card_platform.qip $path]} {set trial_found 1}
        incr checked
    }
}
if {!$overlay_found || !$trial_found} {error "Trial closure or overlay is not assigned"}
project_close
set result [open [file join [file dirname [info script]] project-check.json] w]
puts $result [format {{"project_open":true,"direct_assignments_checked":%d,"compilation_run":false}} $checked]
close $result
puts "PASS Quartus project opens; $checked direct source/IP/constraint assignments exist; no compile run"
