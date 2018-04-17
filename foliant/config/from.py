'''
Extension for Foliant to generate the documentation from multiple sources.

Resolves ``!from`` YAML tag in the project config.
Replaces the value of the tag with ``chaptres`` section
of related subproject. The subproject location may be
specified as a local path, or as a Git repository with
optional revision (branch name, commit hash or another
reference). Examples: ``local_path``,
``https://github.com/foliant-docs/docs.git``,
``https://github.com/foliant-docs/docs.git#master``.
'''

from yaml import add_constructor, load
from shutil import move, rmtree
from pathlib import Path
from importlib import import_module
from typing import Dict
from subprocess import run, CalledProcessError, PIPE, STDOUT

from foliant.config.base import BaseParser


class Parser(BaseParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._src_dir_path = Path(self._get_multiproject_config()['src_dir']).expanduser()
        self._cache_dir_path = self.project_path / '.multiprojectcache'
        self._subproject_config_file_name = self.config_path.name

        add_constructor('!from', self._resolve_from_tag)

    def _get_multiproject_config(self) -> Dict:
        def _fake_resolve_from_tag(_, node):
            return node.value

        add_constructor('!from', _fake_resolve_from_tag)

        with open(self.config_path) as multiproject_config_file:
            multiproject_config = {**self._defaults, **load(multiproject_config_file)}
            return multiproject_config

    def _sync_repo(self, repo_url: str, revision: str or None = None) -> Path:
        repo_name = repo_url.split('/')[-1].rsplit('.', maxsplit=1)[0]
        repo_path = self._cache_dir_path / repo_name

        try:
            run(
                f'git clone {repo_url} {repo_path}',
                shell=True,
                check=True,
                stdout=PIPE,
                stderr=STDOUT
            )

        except CalledProcessError:
            run(
                'git pull',
                cwd=repo_path,
                shell=True,
                check=True,
                stdout=PIPE,
                stderr=STDOUT
            )

        if revision:
            run(
                f'git checkout {revision}',
                cwd=repo_path,
                shell=True,
                check=True,
                stdout=PIPE,
                stderr=STDOUT
            )

        return repo_path

    def _get_chapters_with_overwritten_paths(self, chapters: Dict, subproject_name: str) -> Dict:

        def _recursive_process_chapters(chapters_subset, subproject_name):
            if isinstance(chapters_subset, dict):
                new_chapters_subset = {}
                for key, value in chapters_subset.items():
                    new_chapters_subset[key] = _recursive_process_chapters(value, subproject_name)

            elif isinstance(chapters_subset, list):
                new_chapters_subset = []
                for item in chapters_subset:
                    new_chapters_subset.append(_recursive_process_chapters(item, subproject_name))

            elif isinstance(chapters_subset, str):
                if chapters_subset.endswith('.md'):
                    new_chapters_subset = f'{subproject_name}/{chapters_subset}'

                else:
                    new_chapters_subset = chapters_subset

            else:
                new_chapters_subset = chapters_subset

            return new_chapters_subset

        new_chapters = _recursive_process_chapters(chapters, subproject_name)

        return new_chapters

    def _resolve_from_tag(self, _, node) -> Dict:
        subproject_location = node.value

        if subproject_location.find('://') >= 0:
            subproject_location_parts = subproject_location.split('#', maxsplit=1)
            repo_url = subproject_location_parts[0]
            revision = None

            if len(subproject_location_parts) == 2:
                revision = subproject_location_parts[1]

            subproject_dir_path = self._sync_repo(repo_url, revision)

        else:
            subproject_dir_path = Path(subproject_location).expanduser()

        subproject_config_file_path = subproject_dir_path / self._subproject_config_file_name

        with open(subproject_config_file_path) as subproject_config_file:
            subproject_config = load(subproject_config_file)

        subproject_title = subproject_config['title']
        subproject_chapters = {subproject_title: subproject_config['chapters']}

        subproject_name = subproject_dir_path.name

        make_module = import_module('foliant.cli.make')
        preprocessed_subproject_dir_path = Path(make_module.Cli().make(target='pre', project_path=subproject_dir_path))

        rmtree(self._src_dir_path / subproject_name, ignore_errors=True)
        move(preprocessed_subproject_dir_path, self._src_dir_path / subproject_name)

        return self._get_chapters_with_overwritten_paths(subproject_chapters, subproject_name)
