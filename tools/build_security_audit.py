"""Build OpenSCAP and its missing libraries against an existing KIKI SDK.

The SDK is copied before installing new headers/libraries; the input SDK is never changed.
Source archives must match the operator-reviewed input lock.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys,tarfile,urllib.request
from pathlib import Path
from types import SimpleNamespace


def main():
    p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);p.add_argument('--package-only',action='store_true');p.add_argument('--only');a=p.parse_args()
    sys.path.insert(0,str(a.tools));import ki2build
    a.work.mkdir(parents=True,exist_ok=True);sdk=a.work/'sdk'
    if not sdk.exists():subprocess.run(['cp','-a','--reflink=auto',str(a.sdk),str(sdk)],check=True)
    libdirs=[sdk/x for x in ['usr/lib','usr/lib64','lib64','lib']]
    env=dict(os.environ,PKG_CONFIG_SYSROOT_DIR=str(sdk),PKG_CONFIG_LIBDIR=':'.join(str(sdk/x) for x in ['usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig']))
    flags='--sysroot='+str(sdk)+' -O2 -pipe -fstack-protector-strong -I'+str(sdk/'usr/include')
    links='--sysroot='+str(sdk)+' -B'+str(sdk/'usr/lib64')+'/ -B'+str(sdk/'lib64')+'/ '+' '.join('-L'+str(d)+' -Wl,-rpath-link,'+str(d) for d in libdirs)+' -Wl,-z,relro,-z,now'
    env.update(CC='cc',CFLAGS=flags,LDFLAGS=links)
    recipes=[];results=[]
    for row in json.loads(a.inputs.read_text())['sources']:
        if a.only and row['name']!=a.only:
            old=json.loads((a.work/'results.json').read_text());recipes.extend(r for r in old['recipes'] if r['name']==row['name']);results.extend(r for r in old['packages'] if r['name']==row['name']);continue
        name=row['name'];archive=a.work/Path(row['url']).name
        if not archive.exists():
            with urllib.request.urlopen(row['url'],timeout=90) as f,archive.open('wb') as out:shutil.copyfileobj(f,out)
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==row['sha256'],name+' source SHA mismatch'
        source=a.work/('source-'+name);source.mkdir(exist_ok=True)
        if not list(source.iterdir()):
            with tarfile.open(archive) as tar:tar.extractall(source,filter='data')
        source=next(source.iterdir());build=a.work/('build-'+name);stage=a.work/('stage-'+name);build.mkdir(exist_ok=True);stage.mkdir(exist_ok=True)
        if name in {'libxslt','xmlsec'}:
            options=['--prefix=/usr','--libdir=/usr/lib','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--disable-static','--enable-shared']
            options+=['--without-python','--without-crypto'] if name=='libxslt' else ['--disable-apps','--disable-docs','--with-openssl='+str(sdk/'usr'),'--without-gnutls','--without-gcrypt','--without-nss','--without-libxslt','--disable-crypto-dl']
            if not a.package_only:
                subprocess.run([str(source/'configure')]+options,cwd=build,env=env,check=True)
                subprocess.run(['make','-j4'],cwd=build,env=env,check=True)
                subprocess.run(['make','DESTDIR='+str(stage),'install'],cwd=build,env=env,check=True)
        else:
            options=['-DCMAKE_INSTALL_PREFIX=/usr','-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_SYSROOT='+str(sdk),
                '-DCMAKE_FIND_ROOT_PATH='+str(sdk),'-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY',
                '-DCMAKE_C_FLAGS='+flags,'-DCMAKE_SHARED_LINKER_FLAGS='+links,'-DCMAKE_EXE_LINKER_FLAGS='+links,
                '-DENABLE_PYTHON3=OFF','-DENABLE_PERL=OFF','-DENABLE_TESTS=OFF','-DENABLE_DOCS=OFF','-DENABLE_SCE=OFF',
                '-DENABLE_OSCAP_UTIL_SSH=OFF','-DENABLE_OSCAP_UTIL_DOCKER=OFF','-DENABLE_OSCAP_UTIL_PODMAN=OFF','-DENABLE_OSCAP_UTIL_VM=OFF',
                '-DENABLE_OSCAP_UTIL_AS_RPM=OFF','-DENABLE_OSCAP_UTIL_IM=OFF','-DENABLE_OSCAP_UTIL_AUTOTAILOR=OFF',
                '-DCMAKE_DISABLE_FIND_PACKAGE_RPM=TRUE','-DCMAKE_DISABLE_FIND_PACKAGE_Ldap=TRUE','-DCMAKE_DISABLE_FIND_PACKAGE_OpenDbx=TRUE',
                '-DCMAKE_DISABLE_FIND_PACKAGE_GConf=TRUE','-DCMAKE_DISABLE_FIND_PACKAGE_Procps=TRUE']
            options+=['-DCMAKE_DISABLE_FIND_PACKAGE_Libyaml=TRUE','-DOPENSCAP_PROBE_INDEPENDENT_YAMLFILECONTENT=OFF']
            if not a.package_only:
                subprocess.run(['cmake','-S',str(source),'-B',str(build)]+options,env=env,check=True)
                subprocess.run(['cmake','--build',str(build),'-j4'],env=env,check=True)
                subprocess.run(['cmake','--install',str(build)],env=dict(env,DESTDIR=str(stage)),check=True)
        if not any(stage.iterdir()):raise ValueError('compiled staging output is missing')
        for path in stage.rglob('*.la'):path.unlink()
        if name!='openscap':subprocess.run(['cp','-a',str(stage)+'/.' ,str(sdk)+'/'],check=True)
        raw={'name':name,'version':row['version'],'release':str(row.get('release',1)),'summary':'KIKI source-built '+name,'license':row['license'],
            'architectures':['x86_64'],'source':{'type':'url','url':row['url'],'sha256':row['sha256']},
            'dependencies':{'build':row.get('dependencies',[]),'runtime':row.get('dependencies',[])},
            'build':{'system':'custom','configure':[],'compile':[],'install':[]}}
        # Preserve executable recipes, not a synthetic no-op build description.
        quote=lambda value:'"'+value.replace(str(sdk),'${KI2_SYSROOT}').replace('"','\\"')+'"'
        if name=='openscap':
            raw['build'].update(configure=['cmake -S "${KI2_SOURCE_DIR}" -B "${KI2_BUILD_DIR}/out" '+' '.join(map(quote,options))],
                compile=['cmake --build "${KI2_BUILD_DIR}/out" -j"${KI2_JOBS}"'],
                install=['DESTDIR="${KI2_DESTDIR}" cmake --install "${KI2_BUILD_DIR}/out"'])
        else:
            raw['build'].update(configure=['cd "${KI2_BUILD_DIR}" && "${KI2_SOURCE_DIR}/configure" '+' '.join(map(quote,options))],
                compile=['make -C "${KI2_BUILD_DIR}" -j"${KI2_JOBS}"'],install=['make -C "${KI2_BUILD_DIR}" DESTDIR="${KI2_DESTDIR}" install',
                'find "${KI2_DESTDIR}" -name "*.la" -delete'])
        raw['build']['env']={'CFLAGS':flags.replace(str(sdk),'${KI2_SYSROOT}'),'LDFLAGS':links.replace(str(sdk),'${KI2_SYSROOT}')}
        recipe=ki2build.normalize_recipe(raw,Path('security-build-lock.json'));recipes.append(raw)
        packages=a.work/'packages/x86_64';packages.mkdir(parents=True,exist_ok=True);dest=packages/ki2build.package_filename(recipe,'x86_64')
        ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,stage,dest,ki2build.stable_hash(ki2build.package_file_manifest(stage)),{})
        results.append({'name':name,'file':str(dest),'sha256':ki2build.file_sha256(dest),'source':raw['source']})
        (a.work/'results.json').write_text(json.dumps({'recipes':recipes,'packages':results},indent=2)+'\n')
        print('KIKI_SECURITY_BUILT '+name,flush=True)


if __name__=='__main__':main()
