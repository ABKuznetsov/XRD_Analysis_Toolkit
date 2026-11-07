"""macOS document declarations shared by normal and secure installers."""
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile

PROJECT_UTI = 'com.xrdphasefinder.xpff'


def document_info(info):
    info = dict(info)
    info['CFBundleDocumentTypes'] = [{
        'CFBundleTypeName': 'XRD Phase Finder Project',
        'CFBundleTypeRole': 'Editor',
        'CFBundleTypeIconFile': 'icon.icns',
        'LSHandlerRank': 'Owner',
        'LSItemContentTypes': [PROJECT_UTI],
        'CFBundleTypeExtensions': ['xpff'],
    }]
    info['UTExportedTypeDeclarations'] = [{
        'UTTypeIdentifier': PROJECT_UTI,
        'UTTypeDescription': 'XRD Phase Finder Project',
        'UTTypeConformsTo': ['public.data'],
        'UTTypeTagSpecification': {'public.filename-extension': ['xpff']},
    }]
    return info


def write_icon(source, target):
    # A PNG-backed ICNS avoids iconutil rejecting an otherwise valid iconset
    # on some build hosts. macOS scales the 1024px representation as needed.
    with tempfile.TemporaryDirectory(prefix='xrd-document-icon-') as directory:
        png = Path(directory) / 'icon.png'
        subprocess.run(['/usr/bin/sips', '-z', '1024', '1024', str(source), '--out', str(png)],
                       check=True, stdout=subprocess.DEVNULL)
        data = png.read_bytes()
        chunk = b'ic10' + struct.pack('>I', len(data)+8) + data
        Path(target).write_bytes(b'icns' + struct.pack('>I', len(chunk)+8) + chunk)


if __name__ == '__main__':
    if sys.argv[1] == '--icon':
        write_icon(sys.argv[2], sys.argv[3])
    else:
        path = Path(sys.argv[1])
        path.write_bytes(plistlib.dumps(document_info(plistlib.loads(path.read_bytes())), sort_keys=False))
