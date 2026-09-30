# kas - setup tool for bitbake based projects
#
# Copyright (c) Peter Hatina, 2021
# Copyright (c) Siemens AG, 2021-2022
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import shutil
import pathlib
import subprocess
import re
import pytest
import json
import logging
import yaml
from types import SimpleNamespace
from kas import kas
from kas.context import create_global_context
from kas.kasusererror import ArgsCombinationError, EnvSetButNotFoundError
from kas.libcmds import SetupHome, SetupSSHAgent
from kas import __version__


def _write_config_with_build_dir(build_dir):
    """
        Copies test.yml to test-build-dir.yml, adding the given
        ``build_dir`` value to the header (bumped to version 24).
    """
    with open('test.yml') as f:
        yml = yaml.safe_load(f)
    yml['header']['version'] = 24
    yml['build_dir'] = build_dir
    with open('test-build-dir.yml', 'w') as f:
        yaml.safe_dump(yml, f)
    return 'test-build-dir.yml'


def mock_global_context():
    def args():
        None
    args.no_color = False
    return create_global_context(args)


@pytest.mark.dirsfromenv
def test_build_dir_is_placed_inside_work_dir_by_default(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    shutil.copytree('tests/test_environment_variables', conf_dir)

    monkeykas.chdir(conf_dir)

    kas.kas(['checkout', 'test.yml'])

    assert (monkeykas.get_kbd() / 'conf').exists()


def test_build_dir_can_be_specified_by_environment_variable(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    build_dir = str(tmpdir / 'test_build_dir')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    monkeykas.setenv('KAS_BUILD_DIR', build_dir)
    kas.kas(['checkout', 'test.yml'])

    assert os.path.exists(os.path.join(build_dir, 'conf'))


def test_build_dir_can_be_specified_by_config_file(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    config = _write_config_with_build_dir('custom-build')
    kas.kas(['checkout', config])

    kas_wd = monkeykas.get_kwd()
    assert (kas_wd / 'custom-build' / 'conf').exists()
    # the default build dir must not have been created
    assert not (kas_wd / 'build').exists()


def test_build_dir_config_file_absolute_path(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    abs_build_dir = str(tmpdir / 'abs-build-dir')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    config = _write_config_with_build_dir(abs_build_dir)
    kas.kas(['checkout', config])

    assert os.path.exists(os.path.join(abs_build_dir, 'conf'))


def test_build_dir_config_file_relative_path_resolves_against_work_dir(
        monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    work_dir = str(tmpdir / 'kas-work')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    os.makedirs(work_dir)
    # cwd (where the config file lives) is intentionally different
    # from KAS_WORK_DIR, to verify the relative build_dir is resolved
    # against the work dir and not against the current directory.
    monkeykas.chdir(conf_dir)
    monkeykas.setenv('KAS_WORK_DIR', work_dir)

    config = _write_config_with_build_dir('relative-build')
    kas.kas(['checkout', config])

    assert os.path.exists(os.path.join(work_dir, 'relative-build', 'conf'))
    assert not os.path.exists(os.path.join(conf_dir, 'relative-build'))


def test_build_dir_environment_variable_overrides_config_file(
        monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    env_build_dir = str(tmpdir / 'env-build-dir')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    config = _write_config_with_build_dir('config-build-dir')
    monkeykas.setenv('KAS_BUILD_DIR', env_build_dir)
    kas.kas(['checkout', config])

    assert os.path.exists(os.path.join(env_build_dir, 'conf'))
    assert not os.path.exists(os.path.join(conf_dir, 'config-build-dir'))


def test_clean_commands_use_build_dir_from_config_file(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    config = _write_config_with_build_dir('custom-build')
    kas.kas(['checkout', config])

    kas_wd = monkeykas.get_kwd()
    custom_build = kas_wd / 'custom-build'
    assert custom_build.exists()
    assert not (kas_wd / 'build').exists()

    # fabricate leftovers to verify each clean command targets the
    # config-specified build dir, not the (unused) default one
    (custom_build / 'tmp-glibc').mkdir()
    (custom_build / 'sstate-cache').mkdir()
    (custom_build / 'sstate-cache' / 'leftover').touch()
    (custom_build / 'downloads').mkdir()
    (custom_build / 'downloads' / 'leftover').touch()

    kas.kas(['clean', config])
    assert not (custom_build / 'tmp-glibc').exists()
    assert (custom_build / 'sstate-cache' / 'leftover').exists()
    assert (custom_build / 'downloads' / 'leftover').exists()

    (custom_build / 'tmp-glibc').mkdir()
    kas.kas(['cleansstate', config])
    assert not (custom_build / 'tmp-glibc').exists()
    assert not (custom_build / 'sstate-cache' / 'leftover').exists()
    assert (custom_build / 'downloads' / 'leftover').exists()

    (custom_build / 'tmp-glibc').mkdir()
    (custom_build / 'sstate-cache' / 'leftover').touch()
    kas.kas(['cleanall', config])
    assert not (custom_build / 'tmp-glibc').exists()
    assert not (custom_build / 'sstate-cache' / 'leftover').exists()
    assert not (custom_build / 'downloads' / 'leftover').exists()

    kas.kas(['purge', config])
    assert not any(custom_build.iterdir())


def test_clean_command_env_var_overrides_config_build_dir(monkeykas, tmpdir):
    conf_dir = str(tmpdir / 'test_env_variables')
    env_build_dir = pathlib.Path(str(tmpdir / 'env-build-dir'))
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    config = _write_config_with_build_dir('config-build-dir')
    monkeykas.setenv('KAS_BUILD_DIR', str(env_build_dir))
    kas.kas(['checkout', config])

    assert (env_build_dir / 'conf').exists()

    (env_build_dir / 'tmp-glibc').mkdir()
    kas.kas(['clean', config])
    assert not (env_build_dir / 'tmp-glibc').exists()


@pytest.mark.dirsfromenv
def test_ssh_agent_setup(monkeykas, tmpdir, capsys):
    conf_dir = str(tmpdir / 'test_ssh_agent_setup')
    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)

    SSH_AUTH_SOCK = '/tmp/ssh-KLTafE/agent.64708'

    with monkeykas.context() as mp:
        envfile = tmpdir / 'env'
        mp.setenv('SSH_AUTH_SOCK', SSH_AUTH_SOCK)
        kas.kas(['shell', '-c', f'env > {envfile}', 'test.yml'])
        env = _get_env_from_file(envfile)
        assert env['SSH_AUTH_SOCK'] == SSH_AUTH_SOCK

    with monkeykas.context() as mp:
        mp.setenv('SSH_AUTH_SOCK', SSH_AUTH_SOCK)
        mp.setenv('SSH_PRIVATE_KEY', 'id_rsa')
        with pytest.raises(ArgsCombinationError):
            kas.kas(['checkout', 'test.yml'])

    privkey_file = f'{tmpdir}/id_ecdsa_test'
    genkey_cmd = ['ssh-keygen', '-f', privkey_file, '-N', '', '-t', 'ecdsa']
    subprocess.check_call(genkey_cmd)
    # ensure we also get the info messages
    log = kas.logging.getLogger()
    log.setLevel(kas.logging.INFO)
    # flush the captured output
    capsys.readouterr()
    with monkeykas.context() as mp:
        mp.setenv('SSH_PRIVATE_KEY_FILE', privkey_file)
        kas.kas(['checkout', 'test.yml'])
        out = capsys.readouterr().err
        assert 'adding SSH key from file' in out
        assert 'ERROR' not in out

    with monkeykas.context() as mp:
        privkey = pathlib.Path(privkey_file).read_text()
        mp.setenv('SSH_PRIVATE_KEY', privkey)
        kas.kas(['checkout', 'test.yml'])
        out = capsys.readouterr().err
        assert 'adding SSH key from env-var' in out
        assert 'ERROR' not in out


def test_ssh_host_key_check_is_only_disabled_in_managed_env(monkeypatch):
    calls = []

    monkeypatch.setattr('kas.libcmds.shutil.which', lambda _: '/usr/bin/ssh')
    monkeypatch.setattr('kas.libcmds.ssh_setup_agent',
                        lambda: calls.append('setup'))
    monkeypatch.setattr('kas.libcmds.ssh_no_host_key_check',
                        lambda: calls.append('disable_host_key_check'))

    SetupSSHAgent().execute(SimpleNamespace(managed_env=False))
    assert calls == ['setup']

    calls.clear()
    SetupSSHAgent().execute(SimpleNamespace(managed_env=True))
    assert calls == ['setup', 'disable_host_key_check']


def _get_env_from_file(filename):
    env = {}
    with filename.open() as f:
        for line in f.readlines():
            key, val = line.split("=", 1)
            env[key] = val.strip()
    return env


def _test_env_section_export(monkeykas, tmpdir, bb_env_var, bb_repo):
    conf_dir = tmpdir / 'test_env_variables'
    env_out = conf_dir / 'env_out'
    bb_env_out = conf_dir / 'bb_env_out'
    init_build_env = conf_dir / 'oe-init-build-env'

    shutil.copytree('tests/test_environment_variables', conf_dir)
    monkeykas.chdir(conf_dir)
    monkeykas.setenv('KAS_CLONE_DEPTH', '1')
    monkeykas.setenv('KAS_PREMIRRORS', 'https://git\\.openembedded\\.org/ '
                     'https://github.com/openembedded/\n')
    # resolve after we chdir'd
    kas_wd = monkeykas.get_kwd()
    kas_bd = monkeykas.get_kbd()

    # Overwrite oe-init-build-env script
    # BB_ENV_* filter variables are only exported by
    # kas when they are already exported in the setup environment script
    script = """#!/bin/sh
    export %s="FOO"
    export PATH="%s/%s/bin:${PATH}"
    """ % (bb_env_var, str(kas_wd), bb_repo)
    init_build_env.write_text(script, encoding=None)
    init_build_env.chmod(0o775)

    # Before executing bitbake, first get the bitbake.conf
    kas.kas(['checkout', 'test_env.yml'])
    shutil.copy(kas_wd / bb_repo / 'conf' / 'bitbake.conf',
                kas_bd / 'conf' / 'bitbake.conf')

    kas.kas(['shell', '-c', 'env > %s' % env_out, 'test_env.yml'])
    kas.kas(['shell', '-c', 'bitbake -e > %s' % bb_env_out, 'test_env.yml'])

    # Check kas environment
    test_env = _get_env_from_file(env_out)

    # Variables with 'None' assigned should not be added to environment
    try:
        _ = test_env['TESTVAR_WHITELIST']
        assert False
    except KeyError:
        assert True

    assert test_env['TESTVAR_DEFAULT_VAL'] == 'BAR'
    assert 'TESTVAR_WHITELIST' in test_env[bb_env_var]

    # Check bitbake's environment
    test_bb_env = {}
    with bb_env_out.open() as f:
        for line in f.readlines():
            if re.match(r'^#', line):
                continue
            match = re.match(r'(^[a-zA-Z0-9_]+)=\"([a-zA-Z0-9_ ]+)\"', line)
            if match:
                key, val = match.group(1), match.group(2)
                test_bb_env[key] = val.strip()

    assert 'TESTVAR_WHITELIST' in test_bb_env[bb_env_var]
    assert test_bb_env["TESTVAR_DEFAULT_VAL"] == "BAR"


# BB_ENV_EXTRAWHITE is deprecated but may still be used
@pytest.mark.online
def test_env_section_export_bb_extra_white(monkeykas, tmpdir):
    _test_env_section_export(monkeykas, tmpdir, 'BB_ENV_EXTRAWHITE',
                             'bitbake_old')


@pytest.mark.online
def test_env_section_export_bb_env_passthrough_additions(monkeykas, tmpdir):
    _test_env_section_export(monkeykas, tmpdir, 'BB_ENV_PASSTHROUGH_ADDITIONS',
                             'bitbake_new')


def test_managed_env_detection(monkeykas):
    with monkeykas.context() as mp:
        mp.setenv('GITLAB_CI', 'true')
        ctx = mock_global_context()
        me = ctx.managed_env
        assert bool(me)
        assert str(me) == 'GitLab CI'
    with monkeykas.context() as mp:
        mp.setenv('GITHUB_ACTIONS', 'true')
        ctx = mock_global_context()
        me = ctx.managed_env
        assert bool(me)
        assert str(me) == 'GitHub Actions'
    with monkeykas.context() as mp:
        mp.setenv('REMOTE_CONTAINERS', 'true')
        mp.setenv('REMOTE_CONTAINERS_FOO', 'bar')
        ctx = mock_global_context()
        me = ctx.managed_env
        assert bool(me)
        assert str(me) == 'VSCode Remote Containers'
        assert ctx.environ['REMOTE_CONTAINERS_FOO'] == 'bar'


@pytest.mark.dirsfromenv
def test_env_file_processing(monkeykas, tmpdir):
    ctx = mock_global_context()
    rcfiles = [
        ('NETRC_FILE', '.netrc'),
        ('NPMRC_FILE', '.npmrc'),
        ('REGISTRY_AUTH_FILE', '.docker/config.json'),
        ('AWS_CONFIG_FILE', '.aws/config'),
        ('AWS_WEB_IDENTITY_TOKEN_FILE', '.aws/web_identity_token')
        # no need to test gitconfig, as tested in test_gitconfig
    ]
    for name, file in rcfiles:
        with monkeykas.context() as mp:
            local_file = tmpdir / '.rcfile'
            with open(local_file, 'w') as f:
                if name in ['NETRC_FILE', 'NPMRC_FILE']:
                    f.write('machine foo\nlogin bar\npassword baz\n')
                elif name in ['AWS_CONFIG_FILE',
                              'AWS_WEB_IDENTITY_TOKEN_FILE']:
                    f.write('[profile foo]\nregion=bar\n')
                elif name == 'REGISTRY_AUTH_FILE':
                    json.dump({'auths': {'example.com': {'auth': 'foo'}}}, f)
                else:
                    f.write('foo: bar\n')
            mp.setenv(name, str(local_file))
            if name in ['AWS_CONFIG_FILE', 'AWS_WEB_IDENTITY_TOKEN_FILE']:
                mp.setenv('AWS_SHARED_CREDENTIALS_FILE', str(local_file))
                mp.setenv('AWS_ROLE_ARN', 'arn:foo')
                if name == 'AWS_WEB_IDENTITY_TOKEN_FILE':
                    mp.setenv('AWS_CONFIG_FILE', str(local_file))
            elif name == 'REGISTRY_AUTH_FILE':
                mp.setenv('CI_JOB_TOKEN', 'foo')
                mp.setenv('CI_REGISTRY_USER', 'reg-user')
                mp.setenv('CI_REGISTRY', 'example.com')
            sh = SetupHome()
            sh.execute(ctx)
            assert (pathlib.Path(sh.tmpdirname) / pathlib.Path(file)).exists()


def test_env_set_but_not_existing(monkeykas):
    with monkeykas.context() as mp:
        mp.setenv('NETRC_FILE', '/path/does/not/exist')
        ctx = mock_global_context()
        with pytest.raises(EnvSetButNotFoundError):
            SetupHome().execute(ctx)


def test_kas_container_version(monkeykas, caplog):
    caplog.set_level(logging.WARNING)
    with monkeykas.context() as mp:
        # not a kas-container call
        mock_global_context()
        assert 'versions do not match' not in caplog.text
        caplog.clear()
    with monkeykas.context() as mp:
        # kas-container call from matching script
        mp.setenv('KAS_CONTAINER_SCRIPT_VERSION', __version__)
        mock_global_context()
        assert 'versions do not match' not in caplog.text
        caplog.clear()
    with monkeykas.context() as mp:
        # kas-container call from older/newer script
        mp.setenv('KAS_CONTAINER_SCRIPT_VERSION', '0.0')
        mock_global_context()
        assert 'versions do not match' in caplog.text
        caplog.clear()
