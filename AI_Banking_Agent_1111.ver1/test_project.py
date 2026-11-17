import subprocess,tempfile,pathlib,json
root=pathlib.Path.cwd(); exe=str(root/'banking.exe'); seed=(root/'account.txt').read_text(); results=[]
def run(name,inputs,expected,code=0):
 with tempfile.TemporaryDirectory() as t:
  p=pathlib.Path(t); (p/'account.txt').write_text(seed)
  args=[exe]
  r=subprocess.run(args,input=inputs,text=True,capture_output=True,cwd=t,timeout=8)
  assert r.returncode==code,(name,r.stdout,r.stderr)
  for s in expected: assert s in r.stdout+r.stderr+(p/'account.txt').read_text(),(name,s,r.stdout,r.stderr)
  results.append(name)
run('VIP transfer fee and persistence','0123\n123456\n4\n0124\n20000\n2\n',['79900.23','120000.12'])
run('normal transfer fee','0124\n654321\n4\n0123\n10000\n2\n',['89900.12','110000.23'])
run('normal withdraw limit','0124\n654321\n3\n2000.01\n2\n',['limit exceeded','100000.12'])
run('VIP withdraw limit','0123\n123456\n3\n3000.01\n2\n',['limit exceeded','100000.23'])
run('negative deposit','0123\n123456\n2\n-1\n2\n',['Invalid amount','100000.23'])
run('deposit and continue','0123\n123456\n2\n0.01\n1\n1\n2\n',['100000.24'])
run('wrong login retries','9999\n0123\n000000\n0124\n654321\n5\n',['Invalid account','Wrong password'])
run('invalid target','0123\n123456\n4\n9999\n2\n',['Invalid account'])
(root/'TEST_RESULTS.json').write_text(json.dumps({'passed':len(results),'tests':results},indent=2))
print(json.dumps(results,indent=2))
