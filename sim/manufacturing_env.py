import json 
import os
import time 
import random 
from collections import OrderedDict, deque
from typing import Dict, Any, Optional
from microsoft_bonsai_api.simulator.client import BonsaiClientConfig, BonsaiClient
from microsoft_bonsai_api.simulator.generated.models import (
    SimulatorState,
    SimulatorInterface,
)
import simpy
import numpy as np 

'''
Simulation environment for multi machine simulation environment. 

'''
from line_config import adj, con_balance, con_join


def get_machines_conveyors_sources_sets(adj):
    adj = OrderedDict(sorted(adj.items()))
    conveyors = set()
    sources = set()
    sinks = set()
    for key in list(adj.keys()):
        for element in adj[key]:
            if ("source" not in element) and ("sink" not in element):
                conveyors.add(element)
            elif "source" in element:
                sources.add(element)
            elif "sink" in element: 
                sinks.add(element)
            else:
                pass 

    return sorted(list(set(adj.keys()))), sorted(list(conveyors)), sorted(list(sources)), sorted(list(sinks))
            
class General:
    machines, conveyors, sources, sinks = get_machines_conveyors_sources_sets(adj)
    number_of_machines = len(machines)   # number of General machines
    number_of_conveyors =  len(conveyors)
    machine_infeed_buffer = 100
    machine_discharge_buffer = 100 # 
    conveyor_capacity = 1000  # in cans 
    num_conveyor_bins = 10  # every conveyor is divided into 10 sections. For approximation and connection purposes  
    machine_min_speed = 10 # cans/second 
    machine_max_speed = 100 # cans/second  
    conveyor_min_speed = 10
    conveyor_max_speed = 100
    # warmup_time = 100  # seconds(s) 
    # downtime_event_prob = 0.1 # probability applied every "downtime-even_gen_mean" to create downtime on a random machine 
    downtime_event_gen_mean = 100  # seconds(s), on average "downtime_event_gen_mean" s a random machine may go down using the proability above 
    downtime_duration_mean = 30  # seconds(s), on average each downtime event lasts.   
    control_frequency = 1  # 0: Control at generation of events, any other number indicates a fixed control frequency
    control_type = 1 # 0: control at fixed time frequency 1: event driven, i.e. when a downtime occurs, 2: both at fixed control frequency and downtime  

class Machine(General):
    '''
    This class represents a General machine, i.e. its states and function   

    '''
    def __init__(self, id , speed):
        super().__init__()
        self.min_speed = General.machine_min_speed
        self.max_speed = General.machine_max_speed
        self.id = id 
        self._speed = speed 
        self._state = 'idle' if speed == 0 else 'active'
        # keep track of the down time event times.  

    @property
    def speed(self):
        return self._speed
    @property
    def state(self):
        return self._state
    
    @speed.setter
    def speed(self, value):
        if not (self.min_speed <= value <= self.max_speed or value == 0):
            raise ValueError(f'speed must be 0 or between {self.min_speed} and {self.max_speed}')
        if self.state == "down":
            self._speed = 0
            print('Illegal action: machine is down, machine speed will be kept zero')
        elif value == 0 and self.state != "down":
            self.state = "idle"
            self._speed = value 
        elif  value > 0:
            self._speed = value 
            self.state = "active"

    @state.setter
    def state(self, state):
        if state not in ("prime","idle", "active", "down"):
            raise ValueError('state must be one of the following prime, idle, active, down')
        self._state = state
        if state == 'down' or state == 'idle':
            self._speed = 0

    def __repr__(self):
        return (f'Machine with id of {self.id} \
                runs at speed of {self.speed} and is in {self.state} mode')
    
class Conveyor(General):

    def __init__(self, id, speed, number_of_bins, env):
        super().__init__()
        self.min_speed = General.conveyor_min_speed
        self.max_speed = General.conveyor_max_speed
        self._speed = speed 
        self.id = id 
        self._state = 'idle' if self._speed == 0 else 'active'
        self.capcity = General.conveyor_capacity
        self.number_of_bins = General.num_conveyor_bins
        ## self.number_of_bins*[bin_capacity]             
        self.bins_capacity = self.capcity/self.number_of_bins 
        ## each bin is a container and has a capacity and initial value  
        for i in range(0, self.number_of_bins):
            #setattr(self, "bin" + str(i), simpy.Container(env, init = self.bins_capacity/2,  capacity = self.bins_capacity))
            setattr(self, "bin" + str(i), self.bins_capacity/2)


    @property
    def speed(self):
        return self._speed
    @property
    def state(self):
        return self._state
   
    @speed.setter
    def speed(self, value):
        if not (self.min_speed <= value <= self.max_speed or value == 0):
            raise ValueError(f'speed must be 0 or between {self.min_speed} and {self.max_speed}')
        if self.state == "down":
            self._speed = 0
            print('Illegal action: machine is down, machine speed will be kept zero')
        elif value == 0 and self.state != "down":
            self.state = "idle"
            self._speed = value 
        elif  value > 0:
            self._speed = value 
            self.state = "active"

    @state.setter
    def state(self, state):
        if state not in ("prime","idle", "active", "down"):
            raise ValueError('state must be one of the following prime, idle, active, down')
        self._state = state
        if state == 'down' or state == 'idle':
            self._speed = 0

    ## need to implement a setter and getter 
    def __repr__(self):
        return (f'Conveyor with id of {self.id}\
            runs at speed of {self.speed} and is in {self.state} mode')

class DES(General):
    def __init__(self,env):
        super().__init__()
        self.env = env
        self.components_speed = {}
        self._initialize_conveyor_buffers()
        self._initialize_machines()
        self.episode_end = False 
        # a flag to identify events that require control 
        self.is_control_downtime_event = 0 
        self.is_control_frequency_event = 0 
        self.downtime_event_times_history = deque(maxlen=10) 

        print(f'components speed are\n:', self.components_speed)
        
    def _initialize_conveyor_buffers(self):
    ## There is no input buffer for machine 1. We can safely assume that it is infinite 
        # note -1: as number of conveyors are one less than total number of machines 
        id = 0 
        for conveyor in General.conveyors:
            setattr(self, conveyor,  Conveyor(id = id, speed = General.conveyor_min_speed, number_of_bins = General.num_conveyor_bins, env = self.env))
            #print(getattr(self, conveyor))
            self.components_speed[conveyor] = General.conveyor_min_speed
            id += 1 
    
    def _initialize_machines(self):
    ## create instance of each machine 
        id = 0 
        for machine in General.machines:
            setattr(self, machine,  Machine(id = id, speed = General.machine_min_speed))
            #print(getattr(self, machine))
            self.components_speed[machine] = General.machine_min_speed
            id += 1 

    def processes_generator(self):  
        print('Started can processing ... ')
        if General.control_type == 0:
            self.env.process(self.control_frequency_update())  
        elif General.control_type == 1:
            self.env.process(self.downtime_generator())
            self.env.process(self.downtime_generator())
        elif General.control_type ==2:
            self.env.process(self.control_frequency_update()) 
            self.env.process(self.downtime_generator())
            self.env.process(self.downtime_generator()) 
        else:
            raise ValueError(f"Only three modes are currently available: fixed control frequency (0) or event driven (1), both (2)")
        
    def control_frequency_update(self):
        while True: 
            ## define event type as control frequency event a ahead of the event 
            self.is_control_frequency_event = 1 
            print(f'................ control at {self.env.now} and event requires control: {self.is_control_frequency_event}...')
            yield self.env.timeout(General.control_frequency)
            ## change the flag to zero, in case other events occur.  
            print('-------------------------------------------')
            print(f'control freq event at {self.env.now} s ...')

         
    def downtime_generator(self):
        '''
        Paramters used in General will be used to generate downtime events on a random machine. 
        '''
        while True:
            # randomly pick a machine
            random_machine = random.choice(list(General.machines))
            self.is_control_downtime_event = 1 
            self.is_control_frequency_event = 0 
            print(f'................ now machine {random_machine} goes down at {self.env.now} and event requires control: {self.is_control_downtime_event}...')
            setattr(eval('self.' + random_machine),'state', 'down')
            yield self.env.timeout(5)
            setattr(eval('self.' + random_machine),'state', 'idle')
            print(f'................ now machine {random_machine} is up at {self.env.now} and event requires control: {self.is_control_downtime_event}...')
            print(f'................ let machines run for a given period of time without any downtime event')
            self.is_control_downtime_event = 0
            yield self.env.timeout(15)

            
    def update_line(self):
        # using brain actions 
        self.update_machines_speed()
        # using brain actions 
        self.update_conveyors_speed()

        # enforcing PLC rules to prevent jamming. This may ignore brain actions if buffers are full. 
        self.plc_control_machine_speed()

        self.update_machine_adjacent_buffers()
        self.update_conveyors_buffers()
        self.update_conveyor_junctions()

    def add_event_time():
        '''
        Once called, will add current simulation time. 
        It will be used to track the occurrence time of downtime events
        '''
        self.downtime_event_times_history.append(self.env.now)

    def intra_event_delta_time():
        '''
        The goal is to keep track of time lapsed between events. 
        potential use: (1) calculate remaining downtime (2) for reward normalization 
        '''
        return self.downtime_event_times_history[-1] - self.downtime_event_times_history[-2]

    def update_remaining_downtime():
        '''
        To inform brain about the remaining downtime time for each machine  
        '''
        delta_t = self.intra_event_delta_time()


    def update_machines_speed(self):
        '''
        update the speed of the machine using brain actions that has written in components_speed[machine] dictionary
        '''  
        for machine in General.machines:
            #print(f'now at {self.env.now} s updating mechine speed')
            updated_speed = self.components_speed[machine]
            setattr(eval('self.' + machine),'speed', updated_speed)
            print(eval('self.' + machine))

    def update_conveyors_speed(self):
        '''
        update the speed of the conveyors using brain actions that has written in components_speed[machine] dictionary
        ''' 
        for conveyor in General.conveyors:
            #print(f'now at {self.env.now} s updating conveyor speed')
            updated_speed = self.components_speed[conveyor]
            setattr(eval('self.' + conveyor),'speed', updated_speed)
            #print(eval('self.' + conveyor))

    def update_machine_adjacent_buffers(self):
        '''
        For each machine, we will look at the adj matrix and update number of cans in their buffers. If the buffer is full, we need to shut down the machine. 
        '''
        ### update machine infeed and discharge buffers according to machine speed 
        for machine in adj.keys():
            adj_conveyors = adj[machine]
            infeed = adj_conveyors[0]
            discharge = adj_conveyors[1]
            delta = getattr(eval('self.'+ machine), 'speed')* General.control_frequency   # amount of cans going from one side to the other side 
            if 'source' not in infeed: 

                level = getattr(getattr(self, infeed), "bin"+ str(General.num_conveyor_bins-1))
                level -= delta

                if level <= 0:
                    level = 0 
                    #TODO: prox empty machine speed = 0   
                setattr(eval('self.' +infeed), "bin"+ str(General.num_conveyor_bins-1), level)

                
            if 'sink' not in discharge:
                # now check buffer full  ....................................TODO:
                level = getattr(getattr(self, discharge), "bin"+ str(0))
                capacity = getattr(getattr(self, discharge), "bins_capacity")
                
                level += delta 

                if level>= capacity:   
                    level = capacity           
                    #TODO: trigger discharge prox full  
                setattr(eval('self.' + discharge ), "bin"+ str(0), level)
    
    def update_conveyors_buffers(self):
        for conveyor in General.conveyors:
            for bin_num in range(1, General.num_conveyor_bins):
                delta2 = getattr(eval('self.'+ conveyor), 'speed')* General.control_frequency
                bin_level =  getattr(getattr(self, conveyor), "bin"+ str(bin_num))
                previous_bin_level = getattr(getattr(self, conveyor), "bin"+ str(bin_num - 1))
                
                
                # now take from previous bin and add to the next bin 
                capacity = getattr(getattr(self, conveyor), "bins_capacity")

                # check if enough cans is available 
                if previous_bin_level< delta2:
                    delta2 = previous_bin_level

                # check not to overflow the cans  
                if bin_level + delta2 > capacity:
                    delta2 = capacity - bin_level

                #update the buffers
                bin_level += delta2
                previous_bin_level -= delta2 
                setattr(eval('self.' + conveyor), "bin"+ str(bin_num), bin_level)
                setattr(eval('self.' + conveyor), "bin"+ str(bin_num - 1), previous_bin_level)


    def update_conveyor_junctions(self):
        '''
        Rules for the junctions: mainly balancing the load between lines. 
        If a junction bin gets full, it can push cans to the neighbor conveyor. 
        '''
        for junction in con_balance:    # balancing load between two line 
            conveyor1 = junction[0]
            conveyor2 = junction[1]
            join_bin = junction[2]
            bin_1_level =  getattr(getattr(self, conveyor1), "bin"+ str(join_bin))
            bin_1_capacity =  getattr(getattr(self, conveyor1), "bins_capacity")

            bin_2_level =  getattr(getattr(self, conveyor2), "bin"+ str(join_bin))
            bin_2_capacity =  getattr(getattr(self, conveyor2), "bins_capacity")

            if bin_1_level < bin_1_capacity and bin_2_level <bin_2_capacity:
                ## don't do any thing if both conveyors are operating below the capacity 
                pass
            elif bin_1_level == bin_1_capacity and bin_2_level<bin_2_capacity:
                ## push cans from bin_1 to bin_2
                delta = min(getattr(eval('self.'+ conveyor1), 'speed')* General.control_frequency, bin_2_capacity-bin_2_level)
                setattr(eval('self.' + conveyor2),"bin"+ str(join_bin) , delta + bin_2_level)
                setattr(eval('self.'+ conveyor1), "bin"+ str(join_bin) , bin_1_level - delta)
            
            elif bin_2_level == bin_2_capacity and bin_1_level<bin_1_capacity:
                # do the opposite 
                delta = min(getattr(eval('self.'+ conveyor2), 'speed')* General.control_frequency, bin_1_capacity-bin_1_level)
                setattr(eval('self.' + conveyor1),"bin"+ str(join_bin) , delta + bin_1_level)
                setattr(eval('self.' + conveyor2), "bin"+ str(join_bin) , bin_2_level - delta)
            else:
                ## bin_2.level == bin_2.capacity and bin_2.level == bin_2.capcity:
                ## do nothing 
                pass 

        for junction in con_join:
            conveyor1 = junction[0]
            conveyor2 = junction[1]
            join_bin = junction[2]
            bin_1_level =  getattr(getattr(self, conveyor1), "bin"+ str(General.num_conveyor_bins-1))
            bin_1_capacity = getattr(getattr(self, conveyor1), "bins_capacity")

            bin_2_level =  getattr(getattr(self, conveyor2), "bin"+ str(join_bin))
            bin_2_capacity = getattr(getattr(self, conveyor2), "bins_capacity")
            if bin_2_level < bin_2_capacity:
                ## always add from first one to the second one if there is room 
                delta = min(getattr(eval('self.'+ conveyor1), 'speed')* General.control_frequency, bin_2_capacity-bin_2_level)

                setattr(eval('self.' + conveyor1),"bin"+ str(join_bin) , bin_1_level - delta)
                setattr(eval('self.' + conveyor2), "bin"+ str(join_bin) , bin_2_level + delta)               
            else:
                pass       
        
    def plc_control_machine_speed(self):
        '''
        rule1: machine should stop, i.e. speed = 0, if its discharge prox is full 
        rule2: machine should stop, i.e. speed = 0, if its infeed prox is empty 
        '''
        for machine in adj.keys():
            adj_conveyors = adj[machine]
            infeed = adj_conveyors[0]
            discharge = adj_conveyors[1]
            if 'source' not in infeed: 
                level = getattr(getattr(self, infeed), "bin"+ str(General.num_conveyor_bins-1))
                if level ==0: 
                    print(f'stopping machine {machine} as infeed prox is empty, i.e the whole conveyor is empty')
                    setattr(eval('self.' + machine), "speed", 0)
                    print(eval('self.' + machine))

                
            if 'sink' not in discharge:
                level = getattr(getattr(self, discharge), "bin"+ str(0))
                capacity = getattr(getattr(self, discharge), "bins_capacity")
                 
                if level== capacity:
                        print(f'stopping machine {machine} as discharge prox is full, i.e. the whole conveyor is full')
                        setattr(eval('self.' + machine), "speed", 0)    
                        print(eval('self.' + machine))
   

    def check_illegal_actions():
        '''
        We will compare brain action with the actual speed. If different then brain action was illegal. 
        '''
        

    def reset(self):
        #self.episode_end = False
        self.processes_generator()      


    def step(self, brain_actions):
    
        # update the speed dictionary for those comming from the brain 
        for key in list(brain_actions.keys()):
            self.components_speed[key] = brain_actions[key]
        # update line using self.component_speed
        self.update_line()
        
        print('Simulation time at step:', self.env.now) 
        
        # step through the controllable event
        self.env.step()

        if self.control_type == 0:
            ## control at fixed frequency 
            while self.is_control_frequency_event == 0:
                self.env.step()

        elif self.control_type == 1: 
            ## control when downtime events occur
            # Step through other events until a controllable event occurs. 
            while self.is_control_downtime_event == 0:
                # step through events until a control event, such as downtime, occurs
                # Some events such as time laps are not control events and are excluded by the flag 
                self.env.step()
        elif self.control_type == 2:
            while self.is_control_frequency_event == 0 or self.is_control_downtime_event == 0:
                self.env.step()
        else:
            raise ValueError(f'unknown control type: {self.control_type}. Only 0:fixed time, 1: downtime event, 2: both at fixed time and downtime event')
        

    def get_states(self):
        '''
        In this section, we will read the following:
        (1) Machine speed, an array indicating speed of all the machines 
        (2) conveyor speed, an array indicating speed of all the conveyors 
        (3) proxes, amount of can accumulations in each bin (Note: Not available in real world )
        (4) if proxes are full (two proxes before and two proxes after each machine is available in real world)
        (5) Throughput, i.e. the production rate from sink, i.e the speed of the last machine (will be used as reward)
        '''
        ## 1
        machines_speed = []
        machines_state = []
        for machine in General.machines:
            machines_speed.append(getattr(eval('self.'+ machine), 'speed'))
            state = getattr(eval('self.'+ machine), 'state')
            ## Bonsai platform can only handle numerical values
            ## Assigning integer values to the states  
            if state == 'active':
                machines_state.append(1)
            elif state == 'idle':
                machines_state.append(0)
            elif state =='down':
                machines_state.append(-1)

        ## 2
        conveyors_speed = []
        conveyors_state = []
        for conveyor in General.conveyors:
            conveyors_speed.append(getattr(eval('self.' + conveyor),'speed'))
            conveyor_state.append(getattr(eval('self.' + conveyor),'state'))

        ## 3,4
        conveyor_buffers = []
        conveyor_buffers_full = []

        ## minus 1, minus2 
        conveyor_infeed_m1_prox_empty = []
        conveyor_infeed_m2_prox_empty = []

        ## plus 1, plus2 
        conveyor_discharge_p1_prox_full = []
        conveyor_discharge_p2_prox_full = []

        for conveyor in General.conveyors:
            buffer = []
            buffer_full = []
            bin_capacity = getattr(getattr(self, conveyor), "bins_capacity")
            for bin_num in range(0, General.num_conveyor_bins):
                buffer.append(getattr(getattr(self, conveyor), "bin"+ str(bin_num)))
                buffer_full.append(int(getattr(getattr(self, conveyor), "bin"+ str(bin_num)) == bin_capacity))
            
            conveyor_infeed_m1_prox_empty.append(int(getattr(getattr(self, conveyor), "bin"+ str(General.num_conveyor_bins-1))) == 0)
            conveyor_infeed_m2_prox_empty.append(int(getattr(getattr(self, conveyor), "bin"+ str(General.num_conveyor_bins-2))) == 0)

            conveyor_discharge_p1_prox_full.append(int(getattr(getattr(self, conveyor), "bin"+ str(0))) == bin_capacity)
            conveyor_discharge_p2_prox_full.append(int(getattr(getattr(self, conveyor), "bin"+ str(1))) == bin_capacity)            

            conveyor_buffers.append(buffer)
            conveyor_buffers_full.append(buffer_full)
        
        ## throughput: 5
        sink_machines_rate = []
        for machine in adj.keys():
            adj_conveyors = adj[machine]
            infeed = adj_conveyors[0]
            discharge = adj_conveyors[1]
            if 'sink' in discharge: 
                sink_machines_rate.append(getattr(eval('self.'+ machine), 'speed'))

        ## illegal actions: 6




        ## downtime remaining time: 7 


            
        states = {'machines_speed': machines_speed,
                  'machines_state': machines_state,
                  'machines_state_sum': sum(machines_state),
                  'conveyors_speed': conveyors_speed,
                  'conveyor_buffers': conveyor_buffers,
                  'conveyor_buffers_full': conveyor_buffers_full,
                  'sink_machines_rate': sink_machines_rate,
                  'sink_machines_rate_sum': sum(sink_machines_rate),
                  'conveyor_infeed_m1_prox_empty': conveyor_infeed_m1_prox_empty,
                  'conveyor_infeed_m2_prox_empty': conveyor_infeed_m2_prox_empty,
                  'conveyor_discharge_p1_prox_full': conveyor_discharge_p1_prox_full,
                  'conveyor_discharge_p2_prox_full': conveyor_discharge_p2_prox_full,        
        }

        return states 
                


if __name__=="__main__":                             
    env = simpy.Environment()
    my_env = DES(env)
    my_env.reset()
    iteration = 0 
    while True:
        my_env.step(brain_actions = {'c0': 50, 'm0': 100, 'm1': 10} )
        #input('Press Enter to continue ...')    
        states = my_env.get_states()
        print(f'iteration is {iteration}')
        iteration += 1 
        if iteration ==100000:
            my_env = DES(env)
            my_env.reset()
            iteration = 0

    



