#!/usr/bin/env python3
#
# Downloads snapshots from artifactory, renames them, confirms the sha hash,
# and then uploads the files back to artifactory.
#
#
# Instructions
#
# - Install jfrog cli https://jfrog.com/getcli/
#
# - Run jfrog config add, to configure credentials. Example:
#
# jfrog config add
# Server ID: server1
# JFrog platform URL: https://boostorg.jfrog.io
# Access token (Leave blank for username and password/API key):
# User: _your_username_
# Password/API key: _your_password_
# Is the Artifactory reverse proxy configured to accept a client certificate? (y/n) [n]? n
# [Info] Encrypting password...
#
# - Run the script. For example, to publish boost_1_76_0
#
# ./publish_release.py 1_76_0
#
# If you want to publish a beta, use the '-b' flag to specify which beta.
# If you want to publish a release candidate, use the '-r' flag to specify which RC.
#
# ./publish_release.py 1_76_0 -r 1       # publishes 1_76_0_rc1
# ./publish_release.py 1_76_0 -b 2       # publishes 1_76_0_b2
# ./publish_release.py 1_76_0 -b 4 -r 2  # publishes 1_76_0_b4_rc2

from optparse import OptionParser
import requests
import shutil
import urllib
import hashlib
import re, os, sys
import json
from pathlib import Path

jfrogURL = "https://boostorg.jfrog.io/artifactory/"


def fileHash(fileName):
    sha256_hash = hashlib.sha256()
    with open(fileName, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def genJSON(snapshotJSON, fileName, incomingSHA):
    with open(snapshotJSON, "r") as f:
        snap = json.load(f)
    newJSON = {}
    newJSON["commit"] = snap["commit"]
    newJSON["file"] = fileName
    if "created" in snap:
        newJSON["created"] = snap["created"]
    newJSON["sha256"] = incomingSHA
    if snap["sha256"] != incomingSHA:
        print("ERROR: Checksum failure for '%s'" % fileName)
        print("Recorded:	%s" % snap["sha256"])
        print("Calculated: %s" % incomingSHA)

    return newJSON


# Copied from https://stackoverflow.com/questions/16694907/download-large-file-in-python-with-requests
def downloadAFile(url, destFile):
    with requests.get(url, stream=True) as r:
        with open(destFile, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def downloadJFROGFiles(sourceRepo, sourceFileName, destFileName, suffix):
    # 	Download two files here:
    # 		boost_X_YY_ZZ-snapshot.Q      -> boost_X_YY_ZZ.Q
    # 		boost_X_YY_ZZ-snapshot.Q.json -> boost_X_YY_ZZ-snapshot.Q.json

    sourceFile = "%s%s" % (sourceFileName, suffix)
    destFile = "%s%s" % (destFileName, suffix)
    jsonFile = "%s.json" % sourceFile
    print("Downloading: %s to %s" % (sourceFile, destFile))
    print("Downloading: %s to %s" % (jsonFile, jsonFile))
    downloadAFile(jfrogURL + sourceRepo + sourceFile, destFile)
    downloadAFile(jfrogURL + sourceRepo + jsonFile, jsonFile)


def copyJFROGFile(sourceRepo, sourceFileName, destRepo, destFileName, suffix):
    # 	Copy a file from one place to another on JFROG, renaming it along the way
    print("Copying: %s%s to %s%s" % (sourceFileName, suffix, destFileName, suffix))
    os.system(
        "jfrog rt cp --flat=true %s%s%s %s%s%s"
        % (sourceRepo, sourceFileName, suffix, destRepo, destFileName, suffix)
    )


def uploadJFROGFile(sourceFileName, destRepo):
    # 	Upload a file to JFROG
    print("Uploading: %s" % (sourceFileName))
    os.system("jfrog rt upload %s %s" % (sourceFileName, destRepo))


#####
parser = OptionParser()
parser.add_option(
    "-b", "--beta", default=None, type="int", help="build a beta release", dest="beta"
)
parser.add_option(
    "-r",
    "--release-candidate",
    default=None,
    type="int",
    help="build a release candidate",
    dest="rc",
)
parser.add_option(
    "-p",
    "--progress",
    default=False,
    action="store_true",
    help="print progress information",
    dest="progress",
)
parser.add_option(
    "-n",
    "--dry-run",
    default=False,
    action="store_true",
    help="download files only",
    dest="dryrun",
)

(options, args) = parser.parse_args()
if len(args) != 1:
    print("Too Many arguments")
    parser.print_help()
    exit(1)

boostVersion = args[0]
dottedVersion = boostVersion.replace("_", ".")
sourceRepo = "main/master/"
if options.beta == None:
    actualName = "boost_%s" % boostVersion
    hostedArchiveName = "boost_%s" % boostVersion
    unzippedArchiveName = "boost_%s" % boostVersion
    destRepo = "main/release/%s/source/" % dottedVersion
else:
    actualName = "boost_%s_b%d" % (boostVersion, options.beta)
    hostedArchiveName = "boost_%s_beta%d" % (boostVersion, options.beta)
    unzippedArchiveName = "boost_%s" % boostVersion
    destRepo = "main/beta/%s.beta%d/source/" % (dottedVersion, options.beta)

if options.rc != None:
    actualName += "_rc%d" % options.rc
    # hostedArchiveName
    # unzippedArchiveName

if options.progress:
    print("Creating release files named '%s'" % actualName)
    if options.dryrun:
        print("## Dry run; not uploading files to JFrog")

suffixes = [".7z", ".zip", ".tar.bz2", ".tar.gz"]
snapshotName = "boost_%s-snapshot" % boostVersion

# Download the files
if options.progress:
    print("Downloading from: %s" % sourceRepo)
for s in suffixes:
    downloadJFROGFiles(sourceRepo, snapshotName, actualName, s)

# Create the JSON files
for s in suffixes:
    sourceFileName = actualName + s
    jsonFileName = sourceFileName + ".json"
    jsonSnapshotName = snapshotName + s + ".json"
    if options.progress:
        print("Writing JSON to: %s" % jsonFileName)
    jsonData = genJSON(jsonSnapshotName, sourceFileName, fileHash(sourceFileName))
    with open(jsonFileName, "w", encoding="utf-8") as f:
        json.dump(jsonData, f, ensure_ascii=False, indent=0)

# Unzip an archive locally in ~/archives/tmp/ and move it to ~/archives/
archiveDir = str(Path.home()) + "/archives"
archiveDirTmp = str(Path.home()) + "/archives/tmp"
archiveName = actualName + ".tar.gz"
Path(archiveDir).mkdir(parents=True, exist_ok=True)
if os.path.isdir(archiveDirTmp):
    shutil.rmtree(archiveDirTmp)
Path(archiveDirTmp).mkdir(parents=True, exist_ok=True)
shutil.copyfile(archiveName, archiveDirTmp + "/" + archiveName)
origDir = os.getcwd()
os.chdir(archiveDirTmp)
os.system("tar -xvf %s" % (archiveName))
os.chdir(archiveDir)
if os.path.isdir(hostedArchiveName):
    shutil.rmtree(hostedArchiveName)
shutil.move(archiveDirTmp + "/" + unzippedArchiveName, hostedArchiveName)
os.chdir(origDir)

# Upload the files to JFROG
if options.progress:
    print("Uploading to: %s" % destRepo)
if not options.dryrun:
    for s in suffixes:
        copyJFROGFile(sourceRepo, snapshotName, destRepo, actualName, s)
        uploadJFROGFile(actualName + s + ".json", destRepo)

# Upload the files to S3
aws_profiles = {
    "production": "boost.org.v2",
    "stage": "stage.boost.org.v2",
    "revsys": "boost.revsys.dev",
    "cppal-dev": "boost.org-cppal-dev-v2",
}
aws_region = "us-east-2"

# Create rclone config file
rclonefilecontents = """[remote1]
type = s3
provider = AWS
env_auth = true
region = us-east-2
"""

os.makedirs(str(Path.home()) + "/.config/rclone", exist_ok=True)
with open(str(Path.home()) + "/.config/rclone/rclone.conf", "w") as f:
    f.writelines(rclonefilecontents)

archivePathLocal = str(Path.home()) + "/archives/" + hostedArchiveName + "/"
if not shutil.which("rclone"):
    print("rclone is not installed. Instructions:")
    print(
        "wget https://downloads.rclone.org/v1.64.0/rclone-v1.64.0-linux-amd64.deb; dpkg -i rclone-v1.64.0-linux-amd64.deb"
    )
elif not Path(str(Path.home()) + "/.aws/credentials").is_file():
    print("AWS credentials are missing. Please add the file ~/.aws/credentials .")
else:
    if not options.dryrun:
        for profile, bucket in aws_profiles.items():

            # AWS cli method:
            # archivePathRemote="s3://" + bucket + "/archives/" + hostedArchiveName + "/"
            # os.system("aws s3 cp --recursive --region %s --profile %s %s %s" % (aws_region, profile, archivePathLocal, archivePathRemote))

            # Rclone method:
            archivePathRemote = (
                "remote1:" + bucket + "/archives/" + hostedArchiveName + "/"
            )
            os.system(
                "export AWS_PROFILE=%s;rclone sync --transfers 16 --checksum %s %s"
                % (profile, archivePathLocal, archivePathRemote)
            )
