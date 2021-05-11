import argparse as arp
import os, pathlib, pandas
import os.path as osp
import numpy as np

from reinforcement_learning import logger
from reinforcement_learning.gym.envs.classic_control.pendulum import PendulumEnv
from reinforcement_learning.gym.envs.classic_control.continuous_mountain_car import Continuous_MountainCarEnv
from reinforcement_learning.gym.envs.box2d.lunar_lander import LunarLanderContinuous
from reinforcement_learning.gym.envs.box2d.bipedal_walker import BipedalWalker

from reinforcement_learning.common.vec_env.subproc_vec_env import SubprocVecEnv
from reinforcement_learning.common.policies import policy_0, policy_1, policy_2

from reinforcement_learning.ppo2.ppo2 import PPO2 as ppo
from reinforcement_learning.acktr.acktr import ACKTR as acktr

env_list = [
    PendulumEnv,
    Continuous_MountainCarEnv,
    BipedalWalker,
    LunarLanderContinuous
]

algorithm_list = [
    ppo,
    acktr
]

policy_list = [
    policy_0,
    policy_1,
    policy_2
]

def make_env(env_class):
    fn = lambda: env_class()
    return fn

def generate_traj(env, model, nsteps):
    n = len(env.remotes)
    states = [[] for _ in range(n)]
    actions = [[] for _ in range(n)]
    obs = env.reset()
    for i in range(nsteps):
        action, state = model.predict(obs)
        next_obs, reward, done, info = env.step(action)
        for e in range(n):
            states[e].append(obs[e])
            actions[e].append(action[e])
        obs = np.array(next_obs)
    return states, actions

def find_checkpoint_with_latest_date(checkpoint_dir, prefix='rl_model_'):
    checkpoint_files = [item for item in os.listdir(checkpoint_dir) if osp.isfile(osp.join(checkpoint_dir, item)) and item.startswith(prefix) and item.endswith('.zip')]
    checkpoint_fpaths = [osp.join(checkpoint_dir, item) for item in checkpoint_files]
    checkpoint_dates = [pathlib.Path(item).stat().st_mtime for item in checkpoint_fpaths]
    idx = sorted(range(len(checkpoint_dates)), key=lambda k: checkpoint_dates[k])
    return checkpoint_fpaths[idx[-1]]

if __name__ == '__main__':

    parser = arp.ArgumentParser(description='Test state-of-art RL alghorithms in OpenAI gym')
    parser.add_argument('-e', '--env', help='Environment index', type=int, default=0)
    parser.add_argument('-n', '--nenvs', help='Number of environments', type=int, default=4)
    parser.add_argument('-s', '--steps', help='Number of episode steps', type=int, default=256)
    parser.add_argument('-u', '--updates', help='Number of updates', type=int, default=10000)
    parser.add_argument('-a', '--algorithm', help='RL algorithm index', type=int, default=0)
    parser.add_argument('-o', '--output', help='Output directory', default='models')
    parser.add_argument('-c', '--cuda', help='Use CUDA', default=False, type=bool)
    parser.add_argument('-t', '--trainer', help='Expert model', default=None)
    args = parser.parse_args()

    if not args.cuda:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    env_class = env_list[args.env]
    nenvs = args.nenvs
    algorithm = algorithm_list[args.algorithm]
    totalsteps = args.steps * args.updates * nenvs
    env_fns = [make_env(env_class) for _ in range(nenvs)]
    env = SubprocVecEnv(env_fns)
    eval_env_fns = [make_env(env_class) for _ in range(1)]
    eval_env = SubprocVecEnv(eval_env_fns)

    if args.trainer is not None:
        postfix = 'bc'
        checkpoint_file = find_checkpoint_with_latest_date('{0}/model_checkpoints/'.format(args.trainer))
        trainer_model = ppo.load(checkpoint_file)
        trainer_model.set_env(env)
        print('Expert model has been successfully loaded from {0}'.format(checkpoint_file))
        try:
            p = pandas.read_csv('{0}/expert_data/'.format(args.trainer))
            trajs = p.values
        except Exception as e:
            trajs = []
            for i in range(100):
                states, actions, next_states, rewards = generate_traj(env, trainer_model, args.steps)
                for se, ae, ne, re in zip(states, actions, next_states, rewards):
                    trajs.append([])
                    for s, a, n, r in zip(se, ae, ne, re):
                        trajs[-1].append(np.hstack([s, a, n, r]))
                    trajs[-1] = np.vstack(trajs[-1])
            trajs = np.vstack(trajs)
            pandas.DataFrame(trajs).to_csv('{0}/expert_data/'.format(args.trainer), index=False, header=False)

        del trainer_model
    else:
        postfix = 'pure'

    for policy in policy_list:
        logdir = f'{args.output}/{env_class.__name__}/{algorithm.__name__}/{policy.__name__}_{postfix}/'
        format_strs = os.getenv('', 'stdout,log,csv').split(',')
        logger.configure(os.path.abspath(logdir), format_strs)
        model = algorithm(policy, env, verbose=1)
        model.learn(total_timesteps=totalsteps)