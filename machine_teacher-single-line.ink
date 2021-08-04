inkling "2.0"
using Number
using Math

## define constants, part of sim config 
const number_of_iterations = 1000
const simulation_time_step = 1 # unitless

## control type: -1: control at fixed time frequency but no downtime event 
## control_type:  0: control at fixed time frequency 
## control type:  1: event driven, i.e. when a downtime occurs
## control type:  2: both at fixed control frequency and downtime
const control_type = 0 # 0 or -1 for this project
## the below control frequency does not apply to control type 1 and will be ignored
const control_frequency = 1 # unitless

## Downtime event config 
## a random interval_downtime_event is generated in the range [interval_downtime_event_mean - interval_downtime_event_dev, interval_downtime_event_mean + interval_downtime_event_dev]
## a random downtime duration is generated in the range [downtime_event_duration_mean - downtime_event_duration_std, downtime_event_duration_mean + downtime_event_duration_std]
const interval_downtime_event_mean = 100  # unitless
const interval_downtime_event_dev = 20 # unitless
const downtime_event_duration_mean = 10  # unitless 
const downtime_event_duration_dev = 3  # unitless
## The following indicate possibility of multiple machines going down in parallel and at overlapping times
## 1 means 0 or 1 machine may go down at any point in time
## 2 means: 0, or 1 or 2 machines may go down at any point in time
## n means: 0 upto n machines may go down at any point in time.
const number_parallel_downtime_events = 1

## plant layout
## Currently only 1 configuration exists 
const layout_configuration = 1 

const down_machine_index = 5 # It can be from -1 for random machine down or 0 to 5 for specific down machine
const initial_bin_level = 50
const bin_maximum_capacity = 100
const num_conveyor_bins = 10
const conveyor_capacity = num_conveyor_bins * bin_maximum_capacity
const machine_min_speed = 10
const machine_max_speed = 100
const machine_initial_speed = 100
# const machine_BF_buffer = machine_max_speed * downtime_event_duration_mean + (10 - downtime_event_duration_mean) * machine_min_speed
# const machine_AF_buffer = machine_max_speed * downtime_event_duration_mean + (10 - downtime_event_duration_mean) * machine_min_speed
const infeed_prox_upper_limit = 50
const infeed_prox_lower_limit = 5
const discharge_prox_upper_limit = 90
const discharge_prox_lower_limit = 30
const infeedProx_index1 = 1
const infeedProx_index2 = 2
const dischargeProx_index1 = 0
const dischargeProx_index2 = 1

type SimState {
    machines_actual_speed: number[6], 
    machines_state: number[6],
    brain_speed: number[6],
    machines_state_sum: number,
    conveyors_speed: number[5],
    conveyors_level: number[5],
    conveyors_previous_level: number[5],
    conveyor_buffers: number[10][5],
    sink_machines_rate_sum: number,  # rate of production in the last simulation step 
    sink_throughput_delta_sum: number,  # amount of product produced between the controls 
    sink_throughput_absolute_sum: number, # absolute sum of all the productions at eny iteration
    conveyor_infeed_m1_prox_empty: number[5],
    conveyor_infeed_m2_prox_empty: number[5],
    conveyor_discharge_p1_prox_full: number[5],
    conveyor_discharge_p2_prox_full: number[5],
    conveyor_previous_infeed_m1_prox_empty: number[5],
    conveyor_previous_infeed_m2_prox_empty: number[5],
    conveyor_previous_discharge_p1_prox_full: number[5],
    conveyor_previous_discharge_p2_prox_full: number[5],
    illegal_machine_actions: number[6],
    remaining_downtime_machines: number[6],
    control_delta_t: number,
    env_time: number,
}

type ObservationState{
    machines_actual_speed: number[6],
    machines_state: number[6],
    brain_speed: number[6],
    conveyors_level: number[5],
    conveyors_previous_level: number[5],
    sink_machines_rate_sum: number,
    sink_throughput_delta_sum: number,
    conveyor_infeed_m1_prox_empty: number[5],
    conveyor_infeed_m2_prox_empty: number[5],
    conveyor_discharge_p1_prox_full: number[5],
    conveyor_discharge_p2_prox_full: number[5], 
    conveyor_previous_infeed_m1_prox_empty: number[5],
    conveyor_previous_infeed_m2_prox_empty: number[5],
    conveyor_previous_discharge_p1_prox_full: number[5],
    conveyor_previous_discharge_p2_prox_full: number[5],
    illegal_machine_actions: number[6],
    remaining_downtime_machines: number[6] 
}

# multiarm bandit actions. 
type SimAction{
    machines_speed: number<0,10,20,30,100,>[6],
}


type SimConfig {
    simulation_time_step: simulation_time_step,
    control_type: control_type,
    control_frequency: control_frequency, 
    interval_downtime_event_mean: interval_downtime_event_mean,  
    interval_downtime_event_dev: interval_downtime_event_dev,
    downtime_event_duration_mean: downtime_event_duration_mean,   
    downtime_event_duration_dev: downtime_event_duration_dev,  
    number_parallel_downtime_events: number_parallel_downtime_events,
    layout_configuration: layout_configuration, 
    down_machine_index: down_machine_index,
    initial_bin_level: initial_bin_level,
    bin_maximum_capacity: bin_maximum_capacity,
    num_conveyor_bins: num_conveyor_bins,
    conveyor_capacity: conveyor_capacity,
    machine_min_speed: machine_min_speed,
    machine_max_speed: machine_max_speed,
    machine_initial_speed: machine_initial_speed,
    # machine_BF_buffer: machine_BF_buffer,
    # machine_AF_buffer: machine_AF_buffer,
    infeed_prox_upper_limit: infeed_prox_upper_limit,
    infeed_prox_lower_limit: infeed_prox_lower_limit,
    discharge_prox_upper_limit: discharge_prox_upper_limit,
    discharge_prox_lower_limit: discharge_prox_lower_limit,
    infeedProx_index1: infeedProx_index1,
    infeedProx_index2: infeedProx_index2, 
    dischargeProx_index1: dischargeProx_index1, 
    dischargeProx_index2: dischargeProx_index2,
}


function Reward(sim_observation: SimState){
    if sim_observation.control_delta_t==0 {
        return  0
    }
    else{
        return sim_observation.sink_throughput_delta_sum/(100*sim_observation.control_delta_t)
    }
}

# irrelevant 
function Terminal(sim_obervation: SimState){
    # terminal condition if more than two machine is down or more than 3 machines in idle mode 
    return sim_obervation.machines_state_sum <7
}

simulator Simulator(action: SimAction, config: SimConfig): SimState {
    # package "MLO0420"
}

graph (input: ObservationState): SimAction {

    concept optimize(input): SimAction {
        curriculum {
            algorithm {
                Algorithm: "SAC",
                #BatchSize: 8000,
                #PolicyLearningRate: 0.001
            }
            training {
                EpisodeIterationLimit: number_of_iterations,
                NoProgressIterationLimit: 500000
            }
            source Simulator
            reward Reward
            

            lesson `learn 1` {
                scenario {
                    simulation_time_step: simulation_time_step,
                    control_type : control_type,
                    control_frequency : control_frequency, 
                    interval_downtime_event_mean : interval_downtime_event_mean,  
                    interval_downtime_event_dev : interval_downtime_event_dev,
                    downtime_event_duration_mean : downtime_event_duration_mean,   
                    downtime_event_duration_dev : downtime_event_duration_dev,  
                    number_parallel_downtime_events : number_parallel_downtime_events,
                    layout_configuration : layout_configuration,
                    down_machine_index: down_machine_index,
                    initial_bin_level: initial_bin_level,
                    bin_maximum_capacity: bin_maximum_capacity,
                    num_conveyor_bins: num_conveyor_bins,
                    conveyor_capacity: conveyor_capacity,
                    machine_min_speed: machine_min_speed,
                    machine_max_speed: machine_max_speed,
                    machine_initial_speed: machine_initial_speed,
                    # machine_BF_buffer: machine_BF_buffer,
                    # machine_AF_buffer: machine_AF_buffer,
                    infeed_prox_upper_limit: infeed_prox_upper_limit,
                    infeed_prox_lower_limit: infeed_prox_lower_limit,
                    discharge_prox_upper_limit: discharge_prox_upper_limit,
                    discharge_prox_lower_limit: discharge_prox_lower_limit,
                    infeedProx_index1: infeedProx_index1,
                    infeedProx_index2: infeedProx_index2, 
                    dischargeProx_index1: dischargeProx_index1, 
                    dischargeProx_index2: dischargeProx_index2,
                }
            }
        }
    }
    output optimize 
}   
