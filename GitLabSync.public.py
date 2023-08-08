#!/usr/bin/python
# -*- coding: utf-8 -*-

import getpass
import os
import subprocess
from datetime import datetime

import requests
from git import Repo
from git.repo.fun import is_git_dir
from git.util import assure_directory_exists


class GitlabBackup:
    def __init__(self, repo):
        # BackUp Path
        self.backup_dir = input('Enter local path(/Users/xxx/Path/to/YourBackupDir): ')
        self.base_url = input('Enter your gitlab domain(http://xxx.example.com:8000): ')
        self.rest_url = self.base_url+'/api/v4'
        # 输入 group id，后续获取当前分组下所有 projects，以及子后代；
        # 输入 project id，后续获取当前 project repo 信息；
        # 输入 'all'，后续获取当前 git 用户所有可见有权限操作的 repo 信息；
        parent_group_id = input('Enter your gitlab\'s parent group id: ')
        self.repo_groups = [parent_group_id]
        self.repos = []
        # TODO: init exclude repo
        self.exclude_repos = []

        self.count = { 'clone': 0, 'update': 0, 'exception': 0 }
        self.exception_info = []

        self.is_single_project = False
        self.repo_id = None
        self.repo_branch = None

        if repo['id'] != '':
            self.repo_id = repo['id']
            try:
                self.repo_name = repo['name']
            except:
                self.repo_name = repo['id']

        if repo['branch'] != '' and repo['branch'] != 'all':
            self.repo_branch = repo['branch']

        if self.repo_id and self.repo_id != 'all':
            self.is_single_project = True

        if not os.path.isdir(os.path.join(self.backup_dir)):
            os.mkdir(os.path.join(self.backup_dir))
            # 初始目录并更新chown
            whoami = os.popen('whoami')
            print(f'sudo chown -R {whoami.read().strip()}:staff {os.path.join(self.backup_dir)}')
            os.system(f'sudo chown -R {whoami.read()}:staff {os.path.join(self.backup_dir)}')

        # 获取gitlab access_token
        self.r_token = self.get_access_token()

        # 获取项目
        if not self.repo_id:
            self.get_projects(self.r_token, self.repo_groups[0])
        else:
            self.get_projects(self.r_token, self.repo_id)
        # print(self.repos)

        # clone or pull/fecth
        for repo_item in self.repos:
            try:
                self.clone_or_update_repo(repo_item)
                self.write_log_file(repo_item)
            except:
                self.count_git_action('exception')
                self.exception_info.append(repo_item)
                self.write_log_file(repo_item, type='Exception')

    # 获取gitlab access_token
    def get_access_token(self):
        # Your GitLab account info
        account_name = input('Enter your gitlab account name: ')
        # account_password = input('Enter your password: ')
        account_password = getpass.getpass('Enter your gitlab password: ')

        # Get AccessToken your GitLab account
        postData = dict(grant_type = 'password', username = account_name, password = account_password)
        resToken = requests.post(f'{self.base_url}/oauth/token', data=postData)
        print(f'------resToken------: {resToken.json()}')
        r_token = resToken.json()

        if resToken.status_code != 200:
            print(f'Failed to Get AccessToken from GitLab API, status code: {resToken.status_code}')
            print(f'resToken: {resToken}')
            r_token = []

        self.r_token = r_token

        return r_token

    # # 获取gitlab 项目信息：groups/projects/branchs/tags
    #   The response is:
    #     HTTP/2 200 OK
    #     cache-control: no-cache
    #     content-length: 1103
    #     content-type: application/json
    #     date: Mon, 18 Jan 2016 09:43:18 GMT
    #     link: <https://gitlab.example.com/api/v4/projects/8/issues/8/notes?page=1&per_page=3>; rel="prev", <https://gitlab.example.com/api/v4/projects/8/issues/8/notes?page=3&per_page=3>; rel="next", <https://gitlab.example.com/api/v4/projects/8/issues/8/notes?page=1&per_page=3>; rel="first", <https://gitlab.example.com/api/v4/projects/8/issues/8/notes?page=3&per_page=3>; rel="last"
    #     status: 200 OK
    #     vary: Origin
    #     x-next-page: 3
    #     x-page: 2
    #     x-per-page: 3
    #     x-prev-page: 1
    #     x-request-id: 732ad4ee-9870-4866-a199-a9db0cde3c86
    #     x-runtime: 0.108688
    #     x-total: 8
    #     x-total-pages: 3
    def get_projects(self, r_token, group_id=212):
        # 根据指定的group_id获取所有后代group
        groups_id_list = self.get_descendants_group(group_id)

        # post_headers = {'Authorization': r_token['token_type'] + ' ' + r_token['access_token']}
        post_headers = self.get_authorization_header(r_token)

        if self.is_single_project:
            # 根据指定gitlab project id 获取对应repo信息
            requestUrl = f'{self.rest_url}/projects/{self.repo_id}'
            projects = requests.get(f'{requestUrl}', headers=post_headers)
            if projects.status_code == 200:
                self.add_repo_data(projects.json())

        elif group_id == 'all':
            cur_projects = self.get_projects_data_info(f'{self.rest_url}/projects?order_by=id&sort=desc&per_page=100')
            for project in cur_projects:
                self.add_repo_data(project)

        else:
            # 根据指定gitlab group id 获取repo信息
            for group_id_item in groups_id_list:
                cur_projects = self.get_projects_data_info(f'{self.rest_url}/groups/{group_id_item}/projects?order_by=updated_at&sort=desc&per_page=100')
                for project in cur_projects:
                    self.add_repo_data(project)

        self.write_file(type='Backup', create=True)

    # 根据给定的 api url 获取 projects 相关信息
    def get_projects_data_info(self, request_url):
        post_headers = self.get_authorization_header(self.r_token)
        all_projects = []
        next_page = 1
        while next_page:
            # 获取gitlab上所有repo信息
            requestUrl = request_url + f'&page={next_page}'
            projects = requests.get(f'{requestUrl}', headers=post_headers)

            if projects.status_code == 200:
                all_projects.extend(projects.json())
            else:
                break

            total_page = projects.headers['x-total-pages']
            cur_page = projects.headers['x-page']
            next_page = projects.headers['x-next-page']

            if total_page == cur_page or projects.status_code !=200:
                break

        return all_projects

    # 根据给定的 group id 获取其子后代分组下所有 projects 信息
    def get_descendants_group(self, group_id):
        descendants_group_id = []
        cur_projects = self.get_projects_data_info(f'{self.rest_url}/groups/{group_id}/descendant_groups?order_by=id&sort=desc&per_page=100')

        for group_item in cur_projects:
            descendants_group_id.append(group_item.get('id'))

        return descendants_group_id

    def get_authorization_header(self, r_token):
        cur_token = r_token if r_token and (list(r_token.keys()).count('access_token') != 0) else { 'token_type': 'none', 'access_token': 'none' }

        return {'Authorization': cur_token['token_type'] + ' ' + cur_token['access_token']}

    # 重组 repo 数据，去除冗余字段
    def add_repo_data(self, repo):
        repo = {
            'id': repo['id'],
            'name': repo['name'],
            'path_with_namespace': repo['path_with_namespace'],
            'default_branch': repo['default_branch'],
            'ssh_url_to_repo': repo['ssh_url_to_repo'],
            'http_url_to_repo': repo['http_url_to_repo'],
            'web_url': repo['web_url'],
            'readme_url': repo['readme_url'],
            '_links': repo['_links'],
            'empty_repo': repo['empty_repo'],
            'created_at': repo['created_at'],
            'last_activity_at': repo['last_activity_at']
        }
        if not repo['empty_repo']:
            self.repos.append(repo)

    # clone or update 给定的repo
    def clone_or_update_repo(self, repo):
        """
        Two ways to clone:
        - Repo.clone_from(repo['ssh_url_to_repo'], os.path.join(self.backup_dir, repo['path_with_namespace']), branch=repo['default_branch'])
        - Repo.clone_from(repo['http_url_to_repo'], os.path.join(self.backup_dir, repo['path_with_namespace']), branch=repo['default_branch'])
        """
        cur_repo_dir = os.path.join(self.backup_dir, repo['path_with_namespace'])
        # check it, dirty or clear
        if is_git_dir(os.path.join(cur_repo_dir, '.git')):
            self.repo_stash(cur_repo_dir)
            self.repo_pull(cur_repo_dir)
            self.count_git_action('update')
        else:
            if not repo['empty_repo']:
                # repo_url = repo['http_url_to_repo']
                repo_url = repo['ssh_url_to_repo']
                print(f'-> cloning {repo_url} ...')
                Repo.clone_from(repo_url, os.path.join(self.backup_dir, repo['path_with_namespace']), branch=repo['default_branch'])
                if self.repo_branch:
                    cur_repo = Repo(cur_repo_dir)
                    cur_repo.git.checkout(self.repo_branch)
                self.count_git_action('clone')

    def repo_stash(self, repo_dir):
        cur_repo = Repo(repo_dir)
        if cur_repo.is_dirty():
            cur_branch = self.get_cmdline_print(f'cd {repo_dir} && git branch --show-current')

            print(repo_dir)
            print(f'--> stash branch {cur_branch}')

            cnow = datetime.now().strftime(f'%Y-%m-%d %H:%M:%S.%f')
            cur_repo.git.stash('save', '-a', f'branch {cur_branch} saved at {cnow}')

    def repo_pull(self, repo_dir):
        cur_repo = Repo(repo_dir)
        cur_repo.remotes.origin.fetch()

        cmd_git_branch = f'cd {repo_dir} && git branch -r --sort "committerdate" | tail -n 1'
        newest_origin_branch = self.get_cmdline_print(cmd_git_branch)
        local_branch = newest_origin_branch[7:]

        if not self.repo_branch:
            cur_repo.git.checkout(local_branch)
        else:
            cur_repo.git.checkout(self.repo_branch)

        print('--[U] dir: ', repo_dir)
        print(f'-- origin: {newest_origin_branch} -- local: {local_branch} --')

        cmd_set_upstream = f'cd {repo_dir} && git branch --set-upstream-to={newest_origin_branch} {local_branch}'
        self.get_cmdline_print(cmd_set_upstream, print=False)
        cur_repo.git.pull('-p')

    def to_update_exception(self):
        for repo_item in self.exception_info:
            print('')
            try:
                self.clone_or_update_repo(repo_item)
                self.write_log_file(repo_item)
                print('----: ok')
                self.exception_info.remove(repo_item)
            except:
                print('----: failure')
                self.exception_info.append(repo_item)
                self.write_log_file(repo_item, type='Exception')

    def count_git_action(self, type='clone'):
        self.count[type] = self.count[type] + 1

    def get_cmdline_print(self, cmd_string, print=True):
        if print:
            return subprocess.Popen(cmd_string, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='gbk').communicate()[0].strip()
        else:
            return subprocess.Popen(cmd_string, shell=True, stdout=None, stderr=None).wait()

    def write_file(self, content='', filename='gitlab-projects.json', path='tmp/', type='Info', create=False):
        if not os.path.exists(os.path.join(self.backup_dir, path)):
            os.mkdir(os.path.join(self.backup_dir, path))

        if create:
            action = 'w'
        else:
            action = 'a+'

        with open(os.path.join(self.backup_dir, path, filename), action, encoding='utf-8') as pf:
            cnow = datetime.now().strftime(f'%Y-%m-%d %H:%M:%S.%f')
            if not content:
                pf.write(f'\r- {type.upper()}:\r-- {cnow} --\r{self.repos}\r----------------------------------------------------------------\r')
            else:
                pf.write(f'\r- {type.upper()}: -- {cnow} -- \r{content}\r\r')

    def write_log_file(self, info=None, type='Info'):
        self.write_file(content=info, filename='log', path='tmp/', type=type)

def main():
    """
    run script: python path/to/GitLabSync.public.py

    [Note]:
        - input group id, get all children projects and descendants;
        - input project id, get current project repo information;
        - input 'all', get all projects repo information, if current GitLab's user has valid authorization;
    """
    print('>>>>>>>------ Starting to backup ------>>>>>>>')

    bp = GitlabBackup(repo)

    print('<<<<<<<------ End of backup ------<<<<<<<')
    print('')
    print('--------------------------------')
    print(f'- projects total------: {len(bp.repos)}')
    print(f'- Cloned: {bp.count["clone"]}')
    print(f'- Updated: {bp.count["update"]}')
    print(f'- Exception: {bp.count["exception"]}')
    print('--------------------------------')

    # 询问是否重试更新异常的repo
    if len(bp.exception_info):
        answer = input('是否重试更新异常Repo(y/n)：')
        while answer.lower() == 'y':
            print('-- Let\'s try again ------------------------------')
            bp.to_update_exception()
            break

if __name__ == '__main__':
    repo = {}
    repo['id'] = input('Enter gitlab\'s project or group id: ')
    repo['branch'] = input('Enter branch\'s name(default: master): ')

    main()
