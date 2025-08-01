from physilearning.evaluate import Evaluation
from physilearning.train import Trainer
import yaml
import os
import torch
import numpy as np
import importlib
import stable_baselines3

def get_model(model_name, evaluation):
    #model_name = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/SavedModels/20250206_slv_1_{agent_id}_best_reward.zip'

    fixed_therapy = False
    num_episodes = 1
    print(model_name)
    if not fixed_therapy:
        algorithm_name = evaluation.config['learning']['model']['name']
        try:
            Algorithm = getattr(importlib.import_module('stable_baselines3'), algorithm_name)
        except ModuleNotFoundError:
            print('Algorithm not found in stable_baselines3. Trying sb3_contrib...')
            try:
                Algorithm = getattr(importlib.import_module('sb3_contrib'), algorithm_name)
            except ModuleNotFoundError:
                raise ValueError('Model not found in stable_baselines3 or sb3_contrib')
        else:
            print('Algorithm found in stable_baselines3. Using it...')

        final_score = np.zeros(num_episodes)
        try:
            model = Algorithm.load(model_name)
        except KeyError:
            model = Algorithm.load(model_name, env=evaluation.env, custom_objects=
            {'observation_space': evaluation.env.observation_space, 'action_space': evaluation.env.action_space})

    else:
        final_score = np.zeros(num_episodes)
        model = None
    return model

def get_probs(agent_id = 1, agent_id_2 = 2):
    config_file = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/Configs/20250206_slv_1_{agent_id}.yaml'
    general_config = yaml.load(open(config_file, 'r'), Loader=yaml.FullLoader)

    model_training_path = general_config['eval']['path']
    model_prefix = general_config['eval']['model_prefix']
    model_config_file = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/Configs/20250206_slv_1_{agent_id}.yaml'

    env_type = general_config['eval']['evaluate_on']
    save_name = general_config['eval']['save_name']
    with open(model_config_file, 'r') as f:
        model_config = yaml.load(f, Loader=yaml.FullLoader)
    if env_type == 'same':
        env_type = model_config['env']['type']
        train = Trainer(model_config_file)
    else:
        train = Trainer(config_file)
    train.env_type = env_type
    train.setup_env()
    evaluation = Evaluation(train.env, config_file=f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/Configs/20250206_slv_1_{agent_id}.yaml')

    probing_model_name = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/SavedModels/20250206_slv_1_1_best_reward.zip'
    probing_model = get_model(probing_model_name, evaluation)

    model_name = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/SavedModels/20250206_slv_1_{agent_id}_best_reward.zip'
    model = get_model(model_name, evaluation)

    model_2_name = f'/home/saif/Projects/PhysiLearning/data/GRAPE_important_data/SLV_training/Training/SavedModels/20250206_slv_1_{agent_id_2}_best_reward.zip'
    model2 = get_model(model_2_name, evaluation)
    num_episodes = 50
    # create observation buffer to further sample for probabilities and kl divergence calculations
    obs_buffer = []

    for ptb_run in range(1):

        if evaluation._is_venv():
            obs = evaluation.env.reset()
        else:
            obs, _ = evaluation.env.reset()
        for episode in range(num_episodes):

            done = False
            score = 0
            while not done:
                action, _state = probing_model.predict(obs, deterministic=True)
                if evaluation._is_venv():
                    evaluation.trajectory = evaluation.env.get_attr('trajectory')[0]
                    if evaluation.env.get_attr('observation_type')[0] == 'image':
                        evaluation.image_trajectory = evaluation.env.get_attr('image_trajectory')[0]
                    obs, reward, term, info = evaluation.env.step(action)
                    obs_buffer.append(obs)
                    trunc = info[0]['TimeLimit.truncated']
                else:
                    evaluation.trajectory = evaluation.env.unwrapped.trajectory
                    if evaluation.env.unwrapped.observation_type == 'image':
                        evaluation.image_trajectory = evaluation.env.unwrapped.image_trajectory

                    obs, reward, term, trunc, info = evaluation.env.step(action)
                done = term or trunc
                score += reward


            #print(f'Episode {episode} - Score: {score}')
            filename = os.path.join('Evaluations', save_name + f'{ptb_run}')
            #evaluation.save_trajectory(filename, episode)
            if evaluation._is_venv():
                if evaluation.env.get_attr('time')[0] > 0:
                    obs = evaluation.env.reset()
                else:
                    #print('Episode 0, already reset')
                    pass

            else:
                if evaluation.env.unwrapped.time > 0:
                    obs, _ = evaluation.env.reset()
                else:
                    #print('Episode 0, already reset')
                    pass


        # tranform obs_buffer to pytorch tensor to feed to policy and get probabilities for KL divergence calculation later

        obs_buffer = torch.tensor(obs_buffer, dtype=torch.float32).to(model.device)
        # get the probabilities for the actions
        probs = model.policy.get_distribution(obs_buffer)
        probs2 = model2.policy.get_distribution(obs_buffer)

    return probs, probs2

# set random seed
torch.manual_seed(42)
np.random.seed(42)


probs1, probs2 = get_probs(agent_id = 1, agent_id_2 = 2)
div = stable_baselines3.common.distributions.kl_divergence(probs1, probs2)
scalar_div = div.mean().item()

# create 10 by 10 matrix of KL divergence values
policy_distances = np.ndarray((10))
for agent in range(1, 11):
    for agent_2 in [4]:
        probs1, probs2 = get_probs(agent_id = agent, agent_id_2 = agent_2)
        div = stable_baselines3.common.distributions.kl_divergence(probs1, probs2)
        scalar_div = div.mean().item()
        print(f'Agent {agent} KL divergence: {scalar_div}')
        policy_distances[agent - 1] = scalar_div

# symmetrize the matrix of kl divergence by doing JS = 0.5 * (KL(P||Q) + KL(Q||P))
policy_distances = 0.5 * (policy_distances + policy_distances.T)
print(policy_distances)


