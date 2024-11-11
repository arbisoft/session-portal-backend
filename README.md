# Arbisoft Sessions Portal
[![python](https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue)](https://www.python.org) [![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=green)](https://docs.djangoproject.com/en/4.2/) [![PostgresSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://formulae.brew.sh/formula/postgresql@14)

Setup Guide to setup project from scratch.

- Covered OS:
    * macOs
- Table of Contents
   * [Environment Setup](#environment-setup)
      + [Python 3.12](#python-312)
         - [Install pyenv](#install-pyenv)
         - [Install Python 3.12](#install-python-312)
      + [PIP](#pip)
      + [PostgreSQL](#postgresql)
         - [Install using brew](#install-using-brew)
         - [Start service](#start-service)
   * [Install, Create and Activate Virtual Environment](#install-create-and-activate-virtual-environment)
      + [Install pyenv-virtualenv:](#install-pyenv-virtualenv)
      + [Install dependencies:](#install-dependencies)
   * [Database setup](#database-setup)
   * [Code setup](#code-setup)
      + [Create local.py file](#create-localpy-file)
      + [Modify database settings for local db](#modify-database-settings-for-local-db)
   * [Migrate](#migrate)
   * [Run server](#run-server)

## Environment Setup
### Python 3.12
#### Install pyenv
```bash
$ brew install pyenv
$ echo 'eval "$(pyenv init -)"' >> ~/.zshrc
$ source ~/.zshrc
```
#### Install Python 3.12
```bash
$ pyenv install 3.12
```
### PIP
Install pip3 by running:
```bash
$ curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
$ python get-pip.py
```
### PostgreSQL
#### Install using brew
```bash
$ brew install postgresql@16
```
#### Start service
```bash
$ brew services start postgresql@16
```

## Install, Create and Activate Virtual Environment
### Install pyenv-virtualenv:
Install pyenv-virtualenv with homebrew and add its init to your .zshrc
```bash
$ brew install pyenv-virtualenv
$ echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.zshrc
$ source ~/.zshrc
```
Create a virtual environment (with Python 3.12.6) for the asp project and activate it:
```bash
$ pyenv virtualenv 3.12.6 venv-3.12.6
```
You can set it as default for the repo (activated each time you enter the project's directory). Execute the following from the root of the repo:
```bash
$ pyenv local venv-3.12.6
```
Or, alternatively, you can activate it manually and work while it is on:
```bash
$ pyenv activate venv-3.12.6
```
### Install dependencies:
At project root run the following command to install dependencies:
```bash
$ pip install -r requirements.txt
```
## Database setup
Create a new database using command
```bash
$ createdb asp
```
## Code setup
### Create local.py file
On root of your project run the command
```bash
$ cp arbisoft_sessions_portal/settings/local.example.py arbisoft_sessions_portal/settings/local.py
```
### Modify database settings for local db
Open the `local.py` using an editor
```bash
$ nano arbisoft_sessions_portal/settings/local.py
```
Update the settings in the file for the database, The username is usually the username of your macOs account for example a user with arbisoft as username will set settings as
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        'NAME': 'asp',
        'USER': 'arbisoft',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```
## Migrate
Apply the migrations
```bash
$ python manage.py migrate
```

## Run server
Run the server
```bash
$ python manage.py runserver
```



