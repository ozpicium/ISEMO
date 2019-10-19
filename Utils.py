import numpy as np
from scipy.special import expit
from scipy.misc import logsumexp
import sys, os, time
import copy
from sklearn.linear_model import SGDRegressor
import pickle

PATH = os.path.dirname(os.path.abspath(__file__)) + "\\"

class Params():
    
    params = [10, 2, 3, 5] ### vic. count, maxsave, maxcarry, scanregion

    NONE = -1 ### NONE option

class Cell():
    
    unknown = 20
    filled = 8
    vacant = 1
    
    victim_critical = 18   ###critical (default)
    victim_stable = 4   ###safe, but not rescued...may die if situation gets worse
    victim_rel = 5  
    station = 6
    debris = 7
    path_blockage = 9
    
    #agent = [10, 13, 16, 19] 
    

def reward_blender(w, agents, ISER, noISER):
    
    R_search, R_reloc = w.shared_global_reward()  ### list of global rewards generated by agents
    R = [0 for _ in range(len(agents))]
    
    w_ext = 1000
    w_iser = 1
    
    for i in range(len(agents)):
        
        if agents[i].type == 'Search':
            iser = ISER[i]
            if noISER == 'Search' or noISER == 'All':
                iser = 0
            R[i] += w_ext * R_search + w_iser * iser
        
        elif agents[i].type == 'Aid':
            iser = ISER[i]
            if noISER == 'Aid' or noISER == 'All':
                iser = 0
            R[i] += w_ext * R_reloc + w_iser * iser
            
        elif agents[i].type == 'Relocate':
            iser = ISER[i]
            if noISER == 'Relocate' or noISER == 'All':
                iser = 0
            R[i] += w_ext * R_reloc + w_iser * iser
        
        elif agents[i].type == 'Helper':
            iser = ISER[i]
            if noISER == 'Helper' or noISER == 'All':
                iser = 0
            R[i] += w_ext * (R_search + R_reloc) + w_iser * iser

                        
    return R
    


def edist(p1, p2):  ### point-to-point euclidean distance
        
        xd = p1[0] - p2[0]
        yd = p1[1] - p2[1]
        d = xd**2 + yd**2
        return d
        
        

class Estimator():
    """
    Value Function approximator. 
    """
    
    def __init__(self, lr_critic, lr_term, noptions, agent, coop, testing, model_name):
        
        self.states_seen = []
   
        self.agent = agent

        feats = agent.reset()

        self.noptions = noptions
        
        if not testing:
                self.Qmodels = []
        
                self.betamodels = []
                
                ###### for Value Function Approximation ###################
                for _ in range(noptions):
                    model = SGDRegressor(eta0 = lr_critic, learning_rate="constant")
                    model.partial_fit([self.featurize_state(feats)], [0])
                    self.Qmodels.append(model)
            
                
                ##### for Termination Function Approximation ##############
                for _ in range(noptions):
                    model = SGDRegressor(eta0 = lr_term, learning_rate="constant")   #### we map state to x and x to sigmoid(x)
                    model.partial_fit([self.featurize_state(feats)], [0])    #### start with expit(-2) 
                    self.betamodels.append(model)
                    
        else:
            # load
            with open(PATH + "models\\" + model_name + 'Qmodels.pkl', 'rb') as f:
                self.Qmodels = pickle.load(f)
                #print(self.Qmodels)
            
            with open(PATH + "models\\" + model_name + 'betamodels.pkl', 'rb') as f:
                self.betamodels = pickle.load(f)
            
        
    def featurize_state(self, state):
        """
        Returns the featurized representation for a state.
        """
        
        feat = state
        
        return feat
    
    
    
    def predict_value(self, s, a=None):
        """
        Makes value function predictions.

        """
        features = self.featurize_state(s)
        
        start = time.time()
        
        if not a:
            ret = np.zeros(self.noptions) + (-50000) ### reduce any chance of invalid option selection in softmax policy
  
            for o in range(self.noptions):
                if not self.agent.filterOption(o, 1):
                    ret[o] = self.Qmodels[o].predict([features])[0]
          
        else:
            ret = self.Qmodels[a].predict([features])[0]

        return ret
        
    
    def update_Qmodel(self, s, a, y):
        """
        Updates the estimator parameters for a given state and action towards
        the target y.
        """
        features = self.featurize_state(s)
        
        start = time.time()
        
        try:
            self.Qmodels[a].partial_fit([features], [y])
        except:
            print(features)
            print("Qmodel fail ", y)
    
        #print(time.time() - start)
        
    def predict_termination_arg(self, s, a):

        features = self.featurize_state(s)
        
        if 1:#features not in self.states_seen:

            self.betamodels[a].partial_fit([features], [-2])  ###force init

        ret = self.betamodels[a].predict([features])[0]
        
        return ret
    
    def update_betamodel(self, s, a, y):
        features = self.featurize_state(s)
        self.betamodels[a].partial_fit([features], [y])
        
    
    def save_models(self, model_name):
        
        with open(PATH + "models\\" + model_name + 'Qmodels.pkl','wb') as f:
            pickle.dump(self.Qmodels,f)
            
        with open(PATH + "models\\" + model_name + 'betamodels.pkl','wb') as f:
            pickle.dump(self.betamodels,f)
########################################################################################


        

class SoftmaxPolicy:
    def __init__(self, rng, nactions, estimator, agent, temp=1.):
        
        self.agent = agent
        
        self.rng = rng

        self.temp = temp
        
        self.bit = 0
        
        self.oset = []   #### option set of agent
        
        self.nactions = nactions
        
        self.estimator = estimator

    
    def value(self, phi, action=None):
        return self.estimator.predict_value(phi, action)
        

    def pmf(self, phi):

        val = []
        
        v = self.value(phi)/self.temp

        val = np.exp(v - logsumexp(v))
       
        
        ##### decay
        #self.temp /= 0.0001

        
        return val


    def mask(self,pmf):  ##### invalidate all options which are not in capability set of agent
        pm = pmf
        #return pm
        
        for i in range(len(pm)):
            if self.agent.filterOption(i, 1): #
                pm[i] = 0
            else:
                pm[i] += 0.1  
                
        pm = pm / sum(pm)

         
        #print(self.agent.id, pm)
        
        return pm
        
    def get_output_probas(self, phi):
        return self.mask(self.pmf(phi))
        
    def sample(self, phi):
        o = -1

        start = time.time()
        
        o = int(self.rng.choice(self.nactions, p=self.get_output_probas(phi)))

        if o not in self.oset:
            print("INVALID O")
            sys.exit()


        return o
        
        
        
        

class CoHRLCritic:
    
    def __init__(self, discount, lr, estimator):
        self.lr = lr
        self.discount = discount
        self.estimator = estimator

    def start(self, phi, option):
        self.last_phi = copy.deepcopy(phi)
        self.last_option = option


    def value(self, phi, action=None):
        return self.estimator.predict_value(phi, action)

                
    def advantage(self, phi, option=None):
        values = self.value(phi)

        advantages = values - np.max(values)
        if option is None:
            return advantages
        return advantages[option]
        
        
    def update(self, MDPhistory, phi, option, done):  #### history, s', o'
        
        #print(MDPhistory)
        #return
        
        h = len(MDPhistory)-1  # index tracker
        
        while h >= 0:
            
            update_target = MDPhistory[h][2] ### the reward
            self.last_phi = MDPhistory[h][0] ### pick a state from history
            self.last_option = MDPhistory[h][1] ### pick option from history
            
            inside_hist = 0
            
            if not done:
                current_values = self.value(phi)  ### state s'

                if not inside_hist:
                    update_target += self.discount*(np.max(current_values))   ### Q of state s'...take max if off-policy, take for option if on-policy
                
                else:  ###### commit to one sub-task
                    update_target += self.discount*(current_values[option])  ### option should be equal to last_option since this is history of single subtask, using different varibale for clarity
                    if option != self.last_option:
                        print('unexpected!!')
                        sys.exit()
                    

            self.estimator.update_Qmodel(self.last_phi, self.last_option, update_target)
            
                
            phi = self.last_phi
            option = self.last_option
            
            inside_hist = 1
            
            h -= 1

        return update_target
        
        
        
class ISEMOCritic:
    
    def __init__(self, discount, lr, estimator, terminations):
        self.lr = lr
        self.discount = discount
        self.estimator = estimator
        self.terminations = terminations

    def start(self, phi, option):
        self.last_phi = copy.deepcopy(phi)
        self.last_option = option


    def value(self, phi, action=None):
        return self.estimator.predict_value(phi, action)

                
    def advantage(self, phi, option=None):
        values = self.value(phi)

        advantages = values - np.max(values)
        if option is None:
            return advantages
        return advantages[option]


    def update(self, phi, option, reward, done):
        # One-step update target

        update_target = reward
        
        if not done:
            current_values = self.value(phi)
            
            termination = self.terminations[self.last_option].pmf(phi)
            update_target += self.discount*((1. - termination)*current_values[self.last_option] + termination*np.max(current_values))
                

        self.estimator.update_Qmodel(self.last_phi, self.last_option, update_target)


        self.last_option = option
        self.last_phi = phi

        return update_target
        
        
        


class SigmoidTermination:
    def __init__(self, rng, estimator, option):
        self.rng = rng
        self.force = 0
        self.estimator = estimator
        self.option = option

    def pmf(self, phi):
        
        return 0.3
        
        if not self.force:
            return expit(self.estimator.predict_termination_arg(phi, self.option))
            
        elif self.force == 1:
            return 1
            
        elif self.force == -1:
            return 0


    def sample(self, phi):
        return int(self.rng.uniform() < self.pmf(phi) )  ###### hack!!!!!!!!!!!!!!


    def grad(self, phi):
        terminate = self.pmf(phi)
        return terminate*(1. - terminate), phi
        
        
        
class TerminationGradient:
    
    def __init__(self, terminations, critic, lr, estimator):
        self.terminations = terminations
        self.critic = critic
        self.lr = lr
        self.estimator = estimator


    def update(self, phi, option, eta):
        
        start = time.time()
        
        magnitude, _ = self.terminations[option].grad(phi)
        
        #### here target is the new arg (x) of sigmoid termination function
        y = self.estimator.predict_termination_arg(phi, option) - (self.lr*magnitude*(self.critic.advantage(phi, option) + eta))
        
        self.estimator.update_betamodel(phi, option, y)
        
        #print(time.time() - start)



