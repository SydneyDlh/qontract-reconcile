import logging

import gitlab
import urllib3
import uuid


# The following line will supress
# `InsecureRequestWarning: Unverified HTTPS request is being made`
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitLabApi(object):
    def __init__(self, server, token, project_id=None, ssl_verify=True):
        self.server = server
        self.gl = gitlab.Gitlab(self.server, private_token=token,
                                ssl_verify=ssl_verify)
        self.gl.auth()
        self.user = self.gl.user
        if project_id is not None:
            self.project = self.gl.projects.get(project_id)

    def create_branch(self, new_branch, source_branch):
        data = {
            'branch': new_branch,
            'ref': source_branch
        }
        self.project.branches.create(data)

    def delete_branch(self, branch):
        self.project.branches.delete(branch)

    def delete_file(self, branch_name, file_path, commit_message):
        data = {
            'branch': branch_name,
            'commit_message': commit_message,
            'actions': [
                {
                    'action': 'delete',
                    'file_path': file_path
                    }
            ]
        }
        self.project.commits.create(data)

    def create_mr(self, source_branch, target_branch, title,
                  remove_source_branch=True):
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'remove_source_branch': str(remove_source_branch)
        }
        self.project.mergerequests.create(data)

    def mr_exists(self, title):
        mrs = self.project.mergerequests.list(state='opened')
        for mr in mrs:
            # since we are using a naming convention for these MRs
            # we can determine if a pending MR exists based on the title
            if mr.attributes.get('title') != title:
                continue

            return True

        return False

    def create_delete_user_mr(self, username, paths):
        prefix = 'qontract-reconcile'
        target_branch = 'master'
        branch_name = '{}-delete-{}-{}'.format(
            prefix,
            username,
            str(uuid.uuid4())[0:6]
        )
        title = '[{}] delete user {}'.format(prefix, username)

        if self.mr_exists(title):
            return

        self.create_branch(branch_name, target_branch)

        for path in paths:
            try:
                self.delete_file(branch_name, path, title)
            except gitlab.exceptions.GitlabCreateError as e:
                self.delete_branch(branch_name)
                if str(e) != "400: A file with this name doesn't exist":
                    raise e
                logging.info(
                    "File {} does not exist, not opening MR".format(path)
                )
                return

        self.create_mr(branch_name, target_branch, title)

    def get_project_maintainers(self, repo_url):
        project = self.get_project(repo_url)
        members = project.members.all(all=True)
        return [m['username'] for m in members if m['access_level'] >= 40]

    def get_app_sre_group_users(self):
        app_sre_group = self.gl.groups.get('app-sre')
        return [m for m in app_sre_group.members.list()]

    def check_group_exists(self, group_name):
        groups = self.gl.groups.list()
        group_names = list(map(lambda x: x.name, groups))
        if group_name not in group_names:
            return False
        return True

    def get_string_access_level(self, access):
        if access == 50:
            return "owner"
        elif access == 40:
            return "maintainer"
        elif access == 30:
            return "developer"
        elif access == 20:
            return "reporter"
        else:
            return "guest"

    def get_group_members(self, group_name):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
            return []
        group = self.gl.groups.get(group_name)
        return ([{
                "user": m.username,
                "access_level": self.get_string_access_level(m.access_level)}
                for m in group.members.list()])

    def add_project_member(self, repo_url, user):
        project = self.get_project(repo_url)
        try:
            project.members.create({
                'user_id': user.id,
                'access_level': gitlab.MAINTAINER_ACCESS
            })
        except gitlab.exceptions.GitlabCreateError:
            member = project.members.get(user.id)
            member.access_level = gitlab.MAINTAINER_ACCESS

    def add_group_member(self, group_name, username, access):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
        else:
            group = self.gl.groups.get(group_name)
            user = self.get_user(username)
            if user is not None:
                try:
                    group.members.create({
                        'user_id': user.id,
                        'access_level': access
                        })
                except gitlab.exceptions.GitlabCreateError:
                    member = group.members.get(user.id)
                    member.access_level = access

    def remove_group_member(self, group_name, username):
        group = self.gl.groups.get(group_name)
        user = self.get_user(username)
        if user is not None:
            group.members.delete(user.id)

    def change_access(self, group, user, access):
        access = access.lower()
        if access == "owner":
            access_number = 50
        elif access == "maintainer":
            access_number = 40
        elif access == "developer":
            access_number = 30
        elif access == "reporter":
            access_number = 20
        else:
            access_number = 10
        group = self.gl.groups.get(group)
        member = group.members.get(user.id)
        member.access_level = access_number
        member.save()

    def get_project(self, repo_url):
        repo = repo_url.replace(self.server + '/', '')
        return self.gl.projects.get(repo)

    def get_issues(self, state):
        all_issues = []
        page = 1
        while True:
            issues = self.project.issues.list(state=state, page=page,
                                              per_page=100)
            all_issues.extend(issues)
            if len(issues) < 100:
                break
            page += 1

        return all_issues

    def add_label(self, issue, label):
        note_body = (
            'issue has been marked as {0}. '
            'to remove say `/{0} cancel`').format(label)
        labels = issue.attributes.get('labels')
        labels.append(label)
        issue.notes.create({'body': note_body})
        self.update_labels(issue, labels)

    def remove_label(self, issue, label):
        labels = issue.attributes.get('labels')
        labels.remove(label)
        self.update_labels(issue, labels)

    def update_labels(self, issue, labels):
        editable_issue = \
            self.project.issues.get(issue.attributes.get('iid'), lazy=True)
        editable_issue.labels = labels
        editable_issue.save()

    def close_issue(self, issue):
        issue.state_event = 'close'
        issue.save()

    def get_user(self, username):
        user = self.gl.users.list(search=username)
        if len(user) == 0:
            logging.error(username + " user not found")
            return
        return user[0]

    def get_project_hooks(self, repo_url):
        p = self.get_project(repo_url)
        return p.hooks.list(per_page=100)

    def create_project_hook(self, repo_url, data):
        p = self.get_project(repo_url)
        url = data['job_url']
        trigger = data['trigger']
        hook = {
            'url': url,
            'enable_ssl_verification': 1,
            'note_events': int(trigger == 'mr'),
            'push_events': int(trigger == 'push'),
            'merge_requests_events': int(trigger == 'mr'),
        }
        p.hooks.create(hook)
