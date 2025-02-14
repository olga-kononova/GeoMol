from argparse import ArgumentParser
from rdkit import Chem, Geometry
from rdkit.Chem import AllChem
import numpy as np
import pickle
import pandas as pd
from tqdm import tqdm
import random
import torch
import yaml
import os

from model.model import GeoMol
from model.featurization import featurize_mol_from_smiles
from torch_geometric.data import Batch
from model.inference import construct_conformers


parser = ArgumentParser()
parser.add_argument('--trained_model_dir', type=str)
parser.add_argument('--out', type=str)
parser.add_argument('--test_csv', type=str)
parser.add_argument('--dataset', type=str, default='qm9')
parser.add_argument('--mmff', action='store_true', default=False)
parser.add_argument('--seed', type=int, default=0)
args = parser.parse_args()

random.seed(args.seed)
np.random.seed(args.seed)
torch.manual_seed(args.seed)

device = torch.device(os.getenv("PYTORCH_DEVICE", "cuda"))

trained_model_dir = args.trained_model_dir
test_csv = args.test_csv
dataset = args.dataset
mmff = args.mmff

with open(f'{trained_model_dir}/model_parameters.yml') as f:
    model_parameters = yaml.full_load(f)
model = GeoMol(**model_parameters).to(device)

state_dict = torch.load(f'{trained_model_dir}/best_model.pt', map_location=device)
model.load_state_dict(state_dict, strict=True)
model.eval()

test_data = pd.read_csv(test_csv)

conformer_dict = {}
num = 0
for smi, n_confs, _ in tqdm(test_data.values):
    
    #try:
    # create data object (skip smiles rdkit can't handle)
    tg_data = featurize_mol_from_smiles(smi, dataset=dataset)
    if not tg_data:
        print(f'failed to featurize SMILES: {smi}')
        continue
    
    # generate model predictions
    data = Batch.from_data_list([tg_data]).to(device)
    model(data, inference=True, n_model_confs=n_confs*2)
    
    # set coords
    n_atoms = tg_data.x.size(0)
    model_coords = construct_conformers(data, model)
    mols = []
    for x in model_coords.split(1, dim=1):
        mol = Chem.AddHs(Chem.MolFromSmiles(smi))
        coords = x.squeeze(1).double().cpu().detach().numpy()
        mol.AddConformer(Chem.Conformer(n_atoms), assignId=True)
        for i in range(n_atoms):
            mol.GetConformer(0).SetAtomPosition(i, Geometry.Point3D(coords[i, 0], coords[i, 1], coords[i, 2]))

        if mmff:
            try:
                AllChem.MMFFOptimizeMoleculeConfs(mol, mmffVariant='MMFF94s')
            except Exception as e:
                pass
        mols.append(mol)
        
    conformer_dict[smi] = mols
    
    if len(conformer_dict) > 10000:
        with open(f'{args.out}_{num}.pkl', 'wb') as f:
            pickle.dump(conformer_dict, f)
        conformer_dict = {}
        num += 1
    # except:
    #     pass
    
with open(f'{args.out}_{num}.pkl', 'wb') as f:
    pickle.dump(conformer_dict, f)
                
# save to file
# if args.out:
#     with open(f'{args.out}', 'wb') as f:
#         pickle.dump(conformer_dict, f)
# else:
#     suffix = '_ff' if mmff else ''
#     with open(f'{trained_model_dir}/test_mols{suffix}.pkl', 'wb') as f:
#         pickle.dump(conformer_dict, f)
