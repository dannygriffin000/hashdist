import sys
import os
import subprocess
import shutil
from os.path import join as pjoin, exists as pexists
from textwrap import dedent

from ..formats.config import (
    DEFAULT_STORE_DIR,
    DEFAULT_CONFIG_DIRS,
    DEFAULT_CONFIG_FILENAME_REPR,
    DEFAULT_CONFIG_FILENAME,
    get_config_example_filename
)
from .main import register_subcommand

@register_subcommand
class Remote(object):
    """
    Manage remote build store and source cache (eventually).

    Currently, only common cloud-based storage is supported
    (https://github.com/netheosgithub/pcs_api).


    Example:: First, create a dropbox app for your remote at
    https://www.dropbox.com/developers/apps. Next, add the remote:

        $ hit remote add --pcs="dropbox" --appName="hashdist_ubuntu" --appId="abcd" --appSecret="efjk"

    """
    command = 'remote'

    @staticmethod
    def setup(ap):
        ap.add_argument('subcommand',choices=['add', 'show'])
        ap.add_argument('--pcs', default="dropbox",help='Personal cloud service to use for the remote build store')
        ap.add_argument('--appName', default="hashdist_PLATFORM",help='Name of app you set up via web interface')
        ap.add_argument('--appId', default=None,help='ID assigned to app by pcs')
        ap.add_argument('--appSecret',default=None,help='secret assigned to app by pcs')
        ap.add_argument('--fetch-only',action='store_true',help='only fetch from this remote, never push to it')
    
    @staticmethod
    def run(ctx, args):
        from pcs_api.credentials.app_info_file_repo import AppInfoFileRepository
        from pcs_api.credentials.user_creds_file_repo import UserCredentialsFileRepository
        from pcs_api.credentials.user_credentials import UserCredentials
        from pcs_api.oauth.oauth2_bootstrap import OAuth2BootStrapper
        from pcs_api.storage import StorageFacade
        # Required for registering providers :
        from pcs_api.providers import dropbox, googledrive
        #
        if args.subcommand == 'add':
            ctx.logger.info("Attempting to add remote")
            remote_path = pjoin(DEFAULT_STORE_DIR,"remote")
            try:
                if not os.path.exists(remote_path):
                    os.makedirs(remote_path)
            except:
                ctx.logger.critical("Failed ensuring directory exits:"+`remote_path`)
                exit(1)
            if None in [args.appId, args.appSecret]:
                ctx.logger.critical("Remotes requires both --appId and --appSecret for now")
                exit(1)
            app_info_data = """{pcs}.{appName} = {{ "appId": "{appId}", "appSecret": "{appSecret}", "scope": ["sandbox"] }}""".format(**args.__dict__)
            app_info_path=pjoin(remote_path, "app_info_data.txt")
            user_credentials_path=pjoin(remote_path, "user_credentials_data.txt")
            f = open(app_info_path, "w")
            f.write(app_info_data)
            f.close()
            apps_repo = AppInfoFileRepository(app_info_path)
            user_credentials_repo = UserCredentialsFileRepository(user_credentials_path)
            storage = StorageFacade.for_provider(args.pcs) \
                .app_info_repository(apps_repo, args.appName) \
                .user_credentials_repository(user_credentials_repo) \
                .for_bootstrap() \
                .build()
            bootstrapper = OAuth2BootStrapper(storage)
            bootstrapper.do_code_workflow()
        elif args.subcommand == 'show':
            with open(pjoin(DEFAULT_STORE_DIR,"remote","app_info_data.txt"),"r") as f:
                sys.stdout.write("========\nApp Info\n========\n")
                sys.stdout.writelines(f.readlines())
                sys.stdout.write("\n")
            with open(pjoin(DEFAULT_STORE_DIR,"remote","user_credentials_data.txt"),"r") as f:
                sys.stdout.write("================\nUser Credentials\n================\n")
                sys.stdout.writelines(f.readlines())
                sys.stdout.write("\n")
        else:
            raise AssertionError()

@register_subcommand
class Push(object):
    """
    Push artifacts to remote build store

    Example::

        $ hit push

    """
    command = 'push'

    @staticmethod
    def setup(ap):
        ap.add_argument('--dryrun', action='store_true', help='Show what would happen')
        ap.add_argument('--force', action='store_true', help='Force push of all packages')
        ap.add_argument('--objects', default="build_and_source", help="what kind of objects to push 'build','source', or 'build_and_source'")
    
    @staticmethod
    def run(ctx, args):
        import hashlib,json
        # Required for providers registration :
        from pcs_api.providers import dropbox,googledrive
        #
        from pcs_api.credentials.app_info_file_repo import AppInfoFileRepository
        from pcs_api.credentials.user_creds_file_repo import UserCredentialsFileRepository
        from pcs_api.credentials.user_credentials import UserCredentials
        from pcs_api.storage import StorageFacade
        from pcs_api.bytes_io import (MemoryByteSource, MemoryByteSink,
                                      FileByteSource, FileByteSink,
                                      StdoutProgressListener)
        from pcs_api.models import CPath, CFolder, CBlob, CUploadRequest, CDownloadRequest
        #set up store and change to the artifact root  dir
        from ..core import BuildStore, SourceCache
        if not args.dryrun:
            ctx.logger.info("Setting up cloud storage app")
            remote_path = pjoin(DEFAULT_STORE_DIR,"remote")
            app_info_path=pjoin(remote_path,"app_info_data.txt")
            user_credentials_path=pjoin(remote_path,"user_credentials_data.txt")
            if not os.path.exists(app_info_path):
                ctx.logger.critical('Not found any application information repository file: ' +  `app_info_path`)
                ctx.logger.critical('Refer to documentation and class AppInfoFileRepository to setup pcs_api for a quick test')
                exit(1)
            apps_repo = AppInfoFileRepository(app_info_path)
            if not os.path.exists(user_credentials_path):
                ctx.logger.critical('Not found any users credentials repository file: ' + `user_credentials_path`)
                ctx.logger.critical('Refer to documentation and class UserCredentialsFileRepository to setup pcs_api for a quick test')
                exit(1)
            user_credentials_repo = UserCredentialsFileRepository(user_credentials_path)
            provider_name = apps_repo._app_info.keys()[0].split(".")[0]
            app_info = apps_repo.get(provider_name)
            user_info = user_credentials_repo.get(app_info)
            storage = StorageFacade.for_provider(provider_name) \
                       .app_info_repository(apps_repo,app_info.app_name) \
                       .user_credentials_repository(user_credentials_repo,user_info.user_id) \
                       .build()
            ctx.logger.info("Cloud storage user_id = " + `storage.get_user_id()`)
            ctx.logger.info("Cloud storage quota = "+`storage.get_quota()`)
            ctx.logger.info("Cloud storage is  ready")
            ctx.logger.info("Getting remote manifest")

        if args.objects in ['build','build_and_source']:
            store = BuildStore.create_from_config(ctx.get_config(), ctx.logger)
            os.chdir(store.artifact_root)

            #try loading the local copy of the remote manifest
            try:
                with open(pjoin("..","build_manifest.json"),"r") as manifest_file:
                    local_manifest = json.loads(manifest_file.read())
            except:
                ctx.logger.warn("Using an empty local manifest because build_manifest.json could not be read")
                local_manifest={}
            if args.dryrun:
                ctx.logger.info("Comparing build store to last local copy of remote manifest")
                skipping=''
                pushing=''
                for package in os.listdir(store.artifact_root):
                    for artifact in os.listdir(pjoin(store.artifact_root,package)):
                        if local_manifest.has_key(package) and local_manifest[package].has_key(artifact):
                            skipping += package+"/"+artifact+" Skipping\n"
                        else:
                            pushing += package+"/"+artifact+" Pushing\n"
                sys.stdout.write(skipping+"(Use --force to push skipped artifacts anyway)\n==============================================\n"+pushing)
            else:
                try:
                    remote_manifest_string = MemoryByteSink()
                    fpath = CPath('/bld/')
                    bpath=fpath.add("build_manifest.json")
                    download_request = CDownloadRequest(bpath,remote_manifest_string)
                    download_request.progress_listener(StdoutProgressListener())
                    storage.download(download_request)
                    manifest = json.loads(str(remote_manifest_string.get_bytes()))
                except:
                    ctx.logger.warn("Failed to get remote manifest; all packages will be pushed")
                    manifest = {}
                ctx.logger.info("Writing local copy of remote  manifest")
                with open(pjoin("..","build_manifest.json"),"w") as f:
                    f.write(json.dumps(manifest))
                ctx.logger.info("Calculating which packages to push")
                push_manifest = {}
                for package in os.listdir(store.artifact_root):
                    if not manifest.has_key(package):
                        manifest[package] = {}
                    for artifact in os.listdir(pjoin(store.artifact_root,package)):
                        if manifest[package].has_key(artifact) and not args.force:
                            ctx.logger.info(package+"/"+artifact+" already on remote")
                            #we could also compare the hashes of the binary package here
                        else:
                            if not push_manifest.has_key(package):
                                push_manifest[package]=set()
                            push_manifest[package].add(artifact)
                ctx.logger.info("Artifacts to push"+`push_manifest`)
                for package,artifacts in push_manifest.iteritems():
                    for artifact in artifacts:
                        artifact_path = pjoin(package,artifact)
                        artifact_tgz = artifact+".tar.gz"
                        artifact_tgz_path = pjoin(package,artifact_tgz)
                        sys.stdout.write("Packing and hashing "+`artifact_tgz_path`)
                        subprocess.check_call(["tar","czvf",artifact_tgz_path,artifact_path])
                        with open(artifact_tgz_path,"rb") as f:
                            sha1 = hashlib.sha1()
                            sha1.update(f.read())
                            manifest[package][artifact] = sha1.hexdigest()
                        sys.stdout.write("Pushing "+`artifact_tgz_path`+"\n")
                        fpath = CPath('/bld/'+package)
                        storage.create_folder(fpath)
                        bpath=fpath.add(artifact_tgz)
                        upload_request = CUploadRequest(bpath,FileByteSource(artifact_tgz_path)) 
                        upload_request.progress_listener(StdoutProgressListener())
                        storage.upload(upload_request)
                        sys.stdout.write("Cleaning up and syncing manifest")
                        os.remove(artifact_tgz_path)
                        new_manifest_string = json.dumps(manifest)
                        new_manifest_bytes = bytes(new_manifest_string)
                        manifest_byte_source = MemoryByteSource(new_manifest_bytes)
                        fpath = CPath('/bld/')
                        bpath=fpath.add("build_manifest.json")
                        upload_request = CUploadRequest(bpath,manifest_byte_source).content_type('text/plain')
                        upload_request.progress_listener(StdoutProgressListener())
                        storage.upload(upload_request)
                        with open(pjoin("..","build_manifest.json"),"w") as f:
                            f.write(new_manifest_string)
        if args.objects in ['source','build_and_source']:
            cache = SourceCache.create_from_config(ctx.get_config(), ctx.logger)
            os.chdir(cache.cache_path)
            #try loading the local copy of the remote manifest
            try:
                with open(pjoin("..", "source_manifest.json"), "r") as manifest_file:
                    local_manifest = json.loads(manifest_file.read())
            except:
                ctx.logger.warn("Using an empty local manifest because source_manifest.json could not be read")
                local_manifest={}
            if args.dryrun:
                ctx.logger.info("Comparing source to last local copy of remote manifest")
                skipping=''
                pushing=''
                for subdir in ['files']+[pjoin('packs',pack_type) for pack_type in ['tar.bz2', 'tar.gz', 'zip']]:
                    for source_pack in os.listdir(pjoin(cache.cache_path,subdir)):
                        if local_manifest.has_key(subdir) and source_pack in local_manifest[subdir]:
                            skipping += subdir+"/"+source_pack+" Skipping\n"
                        else:
                            pushing += subdir+"/"+source_pack+" Pushing\n"
                sys.stdout.write(skipping+"(Use --force to push skipped source packs anyway)\n==============================================\n"+pushing)
            else:
                try:
                    remote_manifest_string = MemoryByteSink()
                    fpath = CPath('/src/')
                    bpath=fpath.add("source_manifest.json")
                    download_request = CDownloadRequest(bpath,remote_manifest_string)
                    download_request.progress_listener(StdoutProgressListener())
                    storage.download(download_request)
                    manifest = json.loads(str(remote_manifest_string.get_bytes()))
                except:
                    ctx.logger.warn("Failed to get remote manifest; all packages will be pushed")
                    manifest = {}
                ctx.logger.info("Writing local copy of remote  manifest")
                with open(pjoin("..","source_manifest.json"),"w") as f:
                    f.write(json.dumps(manifest))
                ctx.logger.info("Calculating which packages to push")
                push_manifest = {}
                for subdir in ['files']+[pjoin('packs',pack_type) for pack_type in ['tar.bz2', 'tar.gz', 'zip']]:
                    if not manifest.has_key(subdir):
                        manifest[subdir] = []
                    for source_pack in os.listdir(pjoin(cache.cache_path,subdir)):
                        if source_pack in manifest[subdir] and not args.force:
                            ctx.logger.info(subdir+"/"+source_pack+" already on remote")
                        else:
                            if not push_manifest.has_key(subdir):
                                push_manifest[subdir]=set()
                            push_manifest[subdir].add(source_pack)
                ctx.logger.info("Source packs to push"+`push_manifest`)
                for subdir,source_packs in push_manifest.iteritems():
                    for source_pack in source_packs:
                        manifest[subdir].append(source_pack)
                        source_pack_path = pjoin(subdir,source_pack)
                        sys.stdout.write("Pushing "+`source_pack_path`+"\n")
                        fpath = CPath('/src/'+subdir)
                        storage.create_folder(fpath)
                        bpath=fpath.add(source_pack)
                        upload_request = CUploadRequest(bpath,FileByteSource(source_pack_path)) 
                        upload_request.progress_listener(StdoutProgressListener())
                        storage.upload(upload_request)
                        sys.stdout.write("Syncing manifest")
                        new_manifest_string = json.dumps(manifest)
                        new_manifest_bytes = bytes(new_manifest_string)
                        manifest_byte_source = MemoryByteSource(new_manifest_bytes)
                        fpath = CPath('/src')
                        bpath=fpath.add("source_manifest.json")
                        upload_request = CUploadRequest(bpath,manifest_byte_source).content_type('text/plain')
                        upload_request.progress_listener(StdoutProgressListener())
                        storage.upload(upload_request)
                        with open(pjoin("..","source_manifest.json"),"w") as f:
                            f.write(new_manifest_string)