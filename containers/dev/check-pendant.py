"""Check the embedded Pendant runtime and its shared configuration setting."""
import json
from pathlib import Path
import sys

manifests = list(Path('/opt/pendant').glob('*/package.json'))
assert len(manifests) == 1, 'Expected exactly one image-managed Pendant release'
package = json.loads(manifests[0].read_text())
if len(sys.argv) > 1:
    assert package['version'] == sys.argv[1], 'Unexpected Pendant version'
properties = {}
for section in package['contributes']['configuration']:
    properties.update(section['properties'])
assert 'pendant.agentDir' in properties, 'Pendant must support the private Pi agent directory'
for asset in ('pi-sdk.cjs', 'pi-sdk-worker.cjs', 'core.wasm'):
    assert (manifests[0].parent / 'dist' / asset).is_file(), 'Missing embedded runtime: ' + asset
print(f"PASS Pendant {package['version']} embeds Pi and supports the shared agent directory")
