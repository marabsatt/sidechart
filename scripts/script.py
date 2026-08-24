import os

dir_list = ['assets', 'backend', 'docs', 'frontend', 'src', 'mlops', 'infrastructure']

for dir_name in dir_list:
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
        print(f'Directory {dir_name} created.')
    else:
        print(f'Directory {dir_name} already exists.')
        