"""Generate the small, reviewable KIKI XCCDF/OVAL baseline; no remediation."""
from pathlib import Path
from xml.sax.saxutils import escape

RULES=[
 ('passwd_permissions','passwd 파일 소유권·쓰기 권한','file','/etc/passwd'),
 ('shadow_permissions','shadow 파일 소유권·접근 권한','file','/etc/shadow'),
 ('root_uid_unique','UID 0 계정이 root 한 개뿐인지','observation','root_uid_unique=yes'),
 ('ssh_root_login','SSH root 컨텍스트의 직접 로그인 차단','observation','ssh_root_login=no'),
 ('ssh_empty_password','SSH root 컨텍스트의 빈 암호 인증 차단','observation','ssh_empty_password=no'),
 ('hardlinks','실행 중 protected_hardlinks 설정','observation','hardlinks=1'),
 ('symlinks','실행 중 protected_symlinks 설정','observation','symlinks=1'),
 ('time_sync','지원 시간 동기화 서비스 활성','observation','time_sync=yes'),
 ('firewall','nftables input 체인의 기본 차단 정책','observation','firewall=yes')]

def generate(destination):
 destination.mkdir(parents=True,exist_ok=True)
 x=['<?xml version="1.0"?><Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="xccdf_org.kiki_benchmark_desktop"><status date="2026-10-29">draft</status><title>KIKI Desktop Baseline</title><description>KIKI 자체 설정 기준; CIS/STIG 인증을 의미하지 않음. 자동 수정 없음.</description><platform idref="cpe:/o:kiki:kiki:0.1"/><version>1.0</version><metadata><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">KIKI OS</dc:creator></metadata><Profile id="xccdf_org.kiki_profile_desktop"><title>KIKI Desktop</title><description>설치된 KIKI OS의 읽기 전용 설정 점검</description>']
 for name,_,_,_ in RULES:x.append('<select idref="xccdf_org.kiki_rule_'+name+'" selected="true"/>')
 x.append('</Profile>')
 definitions=[];tests=[];objects=[];states=[]
 for number,(name,title,kind,target) in enumerate(RULES,1):
  rid='xccdf_org.kiki_rule_'+name;oid='oval:org.kiki:def:'+str(number)
  x.append('<Rule id="'+rid+'" selected="true" severity="medium"><title>'+escape(title)+'</title><description>'+escape(title)+'</description><check system="http://oval.mitre.org/XMLSchema/oval-definitions-5"><check-content-ref href="kiki-desktop-oval.xml" name="'+oid+'"/></check></Rule>')
  definitions.append('<definition id="'+oid+'" version="1" class="compliance"><metadata><title>'+escape(title)+'</title><description>'+escape(title)+'</description></metadata><criteria><criterion test_ref="oval:org.kiki:tst:'+str(number)+'" comment="'+escape(title)+'"/></criteria></definition>')
  if kind=='file':
   tests.append('<unix:file_test id="oval:org.kiki:tst:'+str(number)+'" version="1" check="all" check_existence="all_exist" comment="file permissions"><unix:object object_ref="oval:org.kiki:obj:'+str(number)+'"/><unix:state state_ref="oval:org.kiki:ste:'+str(number)+'"/></unix:file_test>')
   objects.append('<unix:file_object id="oval:org.kiki:obj:'+str(number)+'" version="1"><unix:filepath>'+target+'</unix:filepath></unix:file_object>')
   state='<unix:user_id datatype="int">0</unix:user_id><unix:gwrite datatype="boolean">false</unix:gwrite>'
   if name=='shadow_permissions':state+='<unix:oread datatype="boolean">false</unix:oread>'
   state+='<unix:owrite datatype="boolean">false</unix:owrite>'
   if name=='shadow_permissions':state+='<unix:oexec datatype="boolean">false</unix:oexec>'
   states.append('<unix:file_state id="oval:org.kiki:ste:'+str(number)+'" version="1">'+state+'</unix:file_state>')
  else:
   tests.append('<ind:textfilecontent54_test id="oval:org.kiki:tst:'+str(number)+'" version="1" check="all" check_existence="all_exist" comment="effective observation"><ind:object object_ref="oval:org.kiki:obj:'+str(number)+'"/></ind:textfilecontent54_test>')
   objects.append('<ind:textfilecontent54_object id="oval:org.kiki:obj:'+str(number)+'" version="1"><ind:filepath>/run/kiki-security/observed.conf</ind:filepath><ind:pattern operation="pattern match">^'+target+'$</ind:pattern><ind:instance datatype="int">1</ind:instance></ind:textfilecontent54_object>')
 x.append('</Benchmark>')
 definitions.append('<definition id="oval:org.kiki:def:100" version="1" class="inventory"><metadata><title>KIKI OS 0.1</title><description>Explicit KIKI OS identity</description></metadata><criteria><criterion test_ref="oval:org.kiki:tst:100" comment="KIKI OS ID"/></criteria></definition>')
 tests.append('<ind:textfilecontent54_test id="oval:org.kiki:tst:100" version="1" check="all" check_existence="all_exist" comment="KIKI OS identity"><ind:object object_ref="oval:org.kiki:obj:100"/></ind:textfilecontent54_test>')
 objects.append('<ind:textfilecontent54_object id="oval:org.kiki:obj:100" version="1"><ind:filepath>/etc/os-release</ind:filepath><ind:pattern operation="pattern match">^ID=[&quot;\']?kiki[&quot;\']?$</ind:pattern><ind:instance datatype="int">1</ind:instance></ind:textfilecontent54_object>')
 oval='<?xml version="1.0"?><oval_definitions xmlns="http://oval.mitre.org/XMLSchema/oval-definitions-5" xmlns:unix="http://oval.mitre.org/XMLSchema/oval-definitions-5#unix" xmlns:ind="http://oval.mitre.org/XMLSchema/oval-definitions-5#independent"><generator><product_name xmlns="http://oval.mitre.org/XMLSchema/oval-common-5">KIKI security content</product_name><schema_version xmlns="http://oval.mitre.org/XMLSchema/oval-common-5">5.11.1</schema_version><timestamp xmlns="http://oval.mitre.org/XMLSchema/oval-common-5">2026-10-29T00:00:00</timestamp></generator><definitions>'+''.join(definitions)+'</definitions><tests>'+''.join(tests)+'</tests><objects>'+''.join(objects)+'</objects><states>'+''.join(states)+'</states></oval_definitions>'
 (destination/'kiki-desktop-xccdf.xml').write_text(''.join(x)+'\n',encoding='utf-8')
 (destination/'kiki-desktop-oval.xml').write_text(oval+'\n',encoding='utf-8')
 (destination/'kiki-cpe.xml').write_text('<?xml version="1.0"?><cpe-list xmlns="http://cpe.mitre.org/dictionary/2.0"><cpe-item name="cpe:/o:kiki:kiki:0.1"><title xml:lang="en-US">KIKI OS 0.1</title><check system="http://oval.mitre.org/XMLSchema/oval-definitions-5" href="kiki-desktop-oval.xml">oval:org.kiki:def:100</check></cpe-item></cpe-list>\n',encoding='utf-8')

if __name__=='__main__':generate(Path(__file__).resolve().parents[1]/'distro/sources/kiki-security-content/usr/share/kiki-security')
