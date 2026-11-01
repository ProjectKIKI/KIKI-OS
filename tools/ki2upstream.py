"""Bounded upstream release discovery. Discovery never changes a recipe."""
import concurrent.futures
import html
import json
import re
import urllib.parse
import urllib.request


def version_key(value):
    if not re.fullmatch(r'\d+(?:\.\d+)*(?:p\d+)?',str(value)):raise ValueError('stable numeric release required')
    return tuple(int(p) for p in re.findall(r'\d+',str(value)))


def provider(source):
    url=urllib.parse.urlsplit(source.get('url',''));path=url.path
    if url.hostname=='download.gnome.org':
        m=re.match(r'/sources/([^/]+)/',path)
        if m:return {'type':'gnome','project':m[1],'url':'https://download.gnome.org/sources/'+m[1]+'/cache.json'}
    if url.hostname in {'github.com','codeload.github.com'}:
        m=re.match(r'/([^/]+)/([^/]+)/',path)
        if m:return {'type':'github','project':m[1]+'/'+m[2],'url':'https://api.github.com/repos/'+m[1]+'/'+m[2]+'/releases?per_page=5'}
    if url.hostname in {'ftp.gnu.org','download.savannah.gnu.org','download.savannah.nongnu.org','www.x.org','cdn.kernel.org','www.kernel.org','curl.se'}:
        if path.endswith(('.tar.xz','.tar.gz','.tar.bz2','.tar.zst')):
            return {'type':'directory','url':urllib.parse.urlunsplit((url.scheme,url.netloc,path.rsplit('/',1)[0]+'/', '', ''))}
    return None


def fetch(url,validate):
    validate(url)
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            validate(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
    request=urllib.request.Request(url,headers={'User-Agent':'KIKI-update-check/1.0','Accept':'application/json,text/html'})
    with urllib.request.build_opener(Redirect()).open(request,timeout=12) as response:
        raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('upstream metadata too large')
        return raw.decode('utf-8')


def releases(source, info, text):
    current=source['version'];found=[];kind=info['type']
    if kind=='gnome':
        data=json.loads(text)
        # GNOME cache schema: [format_version, {module: {version: {tar.xz: relative path}}}, ...].
        modules=data[1] if isinstance(data,list) else data
        for version,files in modules.get(info['project'],{}).items():
            if not isinstance(files,dict):continue
            relative=files.get('tar.xz') or files.get('tar.gz')
            if relative:found.append({'version':version,'url':urllib.parse.urljoin('https://download.gnome.org/sources/'+info['project']+'/',relative)})
    elif kind=='github':
        for r in json.loads(text):
            if r.get('draft') or r.get('prerelease'):continue
            tag=r.get('tag_name','');m=re.fullmatch(r'(?:v|release[-_]?)?(\d+(?:[._]\d+)*(?:p\d+)?)',tag)
            if not m:continue
            version=m[1].replace('_','.')
            assets=[a for a in r.get('assets',[]) if a.get('name','').endswith(('.tar.xz','.tar.gz','.tar.bz2')) and not any(x in a['name'].lower() for x in ['win32','win64','linux-x','aarch64','amd64','darwin'])]
            # An asset is selected only when its name identifies the release; otherwise use the tagged source archive.
            asset=next((a for a in assets if version in a['name']),None)
            url=asset['browser_download_url'] if asset else 'https://github.com/'+info['project']+'/archive/refs/tags/'+urllib.parse.quote(tag,safe='')+'.tar.gz'
            found.append({'version':version,'url':url,'release_url':r.get('html_url','')})
    else:
        original=urllib.parse.urlsplit(source['url']).path.rsplit('/',1)[-1]
        if current not in original:return []
        prefix,suffix=original.split(current,1)
        pattern=re.compile(re.escape(prefix)+r'(\d+(?:\.\d+)*(?:p\d+)?)'+re.escape(suffix))
        for href in re.findall(r'href=[\'"]([^\'"]+)[\'"]',text,re.I):
            name=urllib.parse.unquote(href.rsplit('/',1)[-1]);m=pattern.fullmatch(name)
            if m:found.append({'version':m[1],'url':urllib.parse.urljoin(info['url'],html.unescape(href))})
    result=[]
    for r in found:
        try:
            key=version_key(r['version']);base=version_key(current)
            # Keep the current major series; e.g. GNOME 50 -> 50.x, Linux 6.1 -> 6.1.x.
            if key<=base or key[0]!=base[0]:continue
            # Older GNOME libraries mix numeric development branches into cache.json.
            # Without upstream stability metadata, follow only the installed minor series.
            if kind=='gnome' and base[0]<40 and key[:2]!=base[:2]:continue
            if kind=='gnome' and any(component>=90 for component in key[1:]):continue
            if source.get('name') in {'linux','linux-headers'} and key[:2]!=base[:2]:continue
            result.append(r)
        except ValueError:continue
    return sorted(result,key=lambda r:version_key(r['version']),reverse=True)


def check_all(rows,validate,reader=None):
    reader=reader or (lambda url:fetch(url,validate))
    grouped={};result=[]
    for row in rows:
        info=provider(row)
        if not info:
            result.append(dict(name=row['name'],current=row['version'],status='manual',message='자동 확인 공급자 미지원 · 원본 링크에서 확인'))
        else:grouped.setdefault(info['url'],[]).append((row,info))
    def check(group):
        url,items=group
        try:
            text=reader(url);out=[]
            for row,info in items:
                newer=releases(row,info,text)
                out.append(dict(name=row['name'],current=row['version'],status='available' if newer else 'current',provider=info['type'],checked_url=url,latest=newer[0] if newer else None))
            return out
        except Exception as error:
            return [dict(name=row['name'],current=row['version'],status='error',message=str(error)[:240],checked_url=url) for row,_ in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for group in pool.map(check,grouped.items()):result.extend(group)
    return sorted(result,key=lambda r:r['name'].casefold())
