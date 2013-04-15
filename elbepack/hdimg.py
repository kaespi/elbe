#!/usr/bin/env python

import os
import sys
import shutil
import string

from treeutils import etree
from optparse import OptionParser
from subprocess import Popen, PIPE, STDOUT

import parted
import _ped

class commanderror(Exception):
    def __init__(self, cmd, returncode):
	self.returncode = returncode
	self.cmd = cmd

    def __repr__(self):
	return "Error: %d returned from Command %s" % (self.returncode, self.cmd)

class asccidoclog(object):
    def __init__(self):
	self.fp = sys.stdout

    def printo(self, text=""):
	self.fp.write(text+"\n")

    def print_raw(self, text):
	self.fp.write(text)

    def h1(self, text):
	self.printo()
	self.printo(text)
	self.printo("="*len(text))
	self.printo()

    def h2(self, text):
	self.printo()
	self.printo(text)
	self.printo("-"*len(text))
	self.printo()

    def table(self):
	self.printo( "|=====================================" )

    def verbatim_start(self):
	self.printo( "------------------------------------------------------------------------------" )

    def verbatim_end(self):
	self.printo( "------------------------------------------------------------------------------" )
	self.printo()

    def do_command(self, cmd, **args):

        if args.has_key("allow_fail"):
            allow_fail = args["allow_fail"]
        else:
            allow_fail = False

	self.printo( "running cmd +%s+" % cmd )
	self.verbatim_start()
	p = Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT )
	output, stderr = p.communicate()
	self.print_raw( output )
	self.verbatim_end()


	if p.returncode != 0:
	    self.printo( "Command failed with errorcode %d" % p.returncode )
            if not allow_fail:
                raise commanderror(cmd, p.returncode)

class fstabentry(object):
    def __init__(self, entry):
	self.label = entry.text("label")
	self.mountpoint = entry.text("mountpoint")
	if entry.has("fs"):
	    self.fstype = entry.text("fs/type")
            self.mkfsopt = entry.text("fs/mkfs", default="")

    def mountdepth(self):
	h = self.mountpoint
	depth = 0

	while True:
	    h, t = os.path.split(h) 
	    if t=='':
		return depth
	    depth += 0


    def get_label_opt(self):
        if self.fstype == "ext4":
            return "-L " + self.label
        if self.fstype == "ext2":
            return "-L " + self.label
        if self.fstype == "ext3":
            return "-L " + self.label
        if self.fstype == "vfat":
            return "-n " + self.label
        if self.fstype == "xfs":
            return "-L " + self.label
        if self.fstype == "btrfs":
            return "-L " + self.label

        return ""

    def losetup( self, outf, loopdev ):
        outf.do_command( 'losetup -o%d --sizelimit %d /dev/%s "%s"' % (self.offset, self.size, loopdev, self.filename) )

def mkfs_mtd( outf, mtd, fslabel ):

    if not mtd.has("ubivg"):
        return

    ubivg = mtd.node("ubivg")
    for v in ubivg:
        if not v.tag == "ubi":
            continue

        label = v.text("label")

        if not fslabel.has_key(label):
            continue

        outf.do_command( "mkfs.ubifs -r /opt/elbe/filesystems/%s -o /opt/elbe/%s.ubifs -m %s -e %s -c %s %s" % (
            label, label,
            ubivg.text("miniosize"),
            ubivg.text("logicaleraseblocksize"),
            ubivg.text("maxlogicaleraseblockcount"),
            fslabel[label].mkfsopt ) )

def build_image_mtd( outf, mtd, fslabel ):

    if not mtd.has("ubivg"):
        return

    ubivg = mtd.node("ubivg")

    if ubivg.has("subpagesize"):
        subp = "-s " + ubivg.text("subpagesize")
    else:
        subp = ""

    outf.do_command( "ubinize %s -o %s -p %s -m %s /opt/elbe/ubi.cfg" % (
        subp,
        mtd.text("name"),
        ubivg.text("physicaleraseblocksize"),
        ubivg.text("miniosize") ) )

    outf.do_command( "echo /opt/elbe/%s >> /opt/elbe/files-to-extract" % mtd.text("name") )


def size_to_int( size ):
    if size[-1] in string.digits:
        return int(size)

    if size.endswith( "M" ):
        unit = 1000*1000
        s = size[:-1]
    elif size.endswith( "MiB" ):
        unit = 1024*1024
        s = size[:-3]
    elif size.endswith( "MB" ):
        unit = 1000*1000
        s = size[:-2]
    if size.endswith( "G" ):
        unit = 1000*1000*1000
        s = size[:-1]
    elif size.endswith( "GiB" ):
        unit = 1024*1024*1024
        s = size[:-3]
    elif size.endswith( "GB" ):
        unit = 1000*1000*1000
        s = size[:-2]
    if size.endswith( "k" ):
        unit = 1000
        s = size[:-1]
    elif size.endswith( "kiB" ):
        unit = 1024
        s = size[:-3]
    elif size.endswith( "kB" ):
        unit = 1000
        s = size[:-2]

    return int(s) * unit


class grubinstaller( object ):
    def __init__( self, outf ):
        self.outf = outf
        self.root = None
        self.boot = None

    def set_boot_entry( self, entry ):
        print "setting boot entry"
        self.boot = entry

    def set_root_entry( self, entry ):
        self.root = entry

    def install( self, opt ):
        if not self.root:
            return

        self.outf.do_command( 'cp -a /dev/loop0 /dev/poop0' )
        self.outf.do_command( 'cp -a /dev/loop1 /dev/poop1' )
        self.outf.do_command( 'cp -a /dev/loop2 /dev/poop2' )

        self.outf.do_command( 'losetup /dev/poop0 "%s"' % self.root.filename )
        self.root.losetup( self.outf, "poop1" )
        self.outf.do_command( 'mount /dev/poop1 %s' % opt.dir )

        if self.boot:
            self.boot.losetup( self.outf, "poop2" )
            self.outf.do_command( 'mount /dev/poop2 %s' % (os.path.join( opt.dir, "boot" ) ) )

        devmap = open( os.path.join( opt.dir, "boot/grub/device.map" ), "w" )
        devmap.write( "(hd0) /dev/poop0\n" )
        devmap.write( "(hd0,%s) /dev/poop1\n" % self.root.number )
        if self.boot:
            devmap.write( "(hd0,%s) /dev/poop2\n" % self.boot.number )

        devmap.close()


        self.outf.do_command( "mount --bind /dev %s" % os.path.join( opt.dir, "dev" ) )
        self.outf.do_command( "mount --bind /proc %s" % os.path.join( opt.dir, "proc" ) )
        self.outf.do_command( "mount --bind /sys %s" % os.path.join( opt.dir, "sys" ) )
        self.outf.do_command( "chroot %s  update-grub2"  % opt.dir )

        self.outf.do_command( "grub-install --no-floppy --grub-mkdevicemap=%s/boot/grub/device.map --root-directory=%s /dev/loop0" % (opt.dir,opt.dir))

        self.outf.do_command( "umount %s" % os.path.join( opt.dir, "dev" ) )
        self.outf.do_command( "umount %s" % os.path.join( opt.dir, "proc" ) )
        self.outf.do_command( "umount %s" % os.path.join( opt.dir, "sys" ) )

        self.outf.do_command( "losetup -d /dev/poop0" )

        if self.boot:
            self.outf.do_command( 'umount /dev/poop2' )
            self.outf.do_command( 'losetup -d /dev/poop2' )

        self.outf.do_command( 'umount /dev/poop1' )
        self.outf.do_command( 'losetup -d /dev/poop1' )

def do_image_hd( outf, hd, fslabel, opt ):

	if not hd.has("partitions"):
	    return

        # Init to 0 because we increment before using it
        partition_number = 0

        sector_size = 512
	s=size_to_int(hd.text("size"))
	size_in_sectors = s / sector_size

	outf.do_command( 'dd if=/dev/zero of="%s" count=%d bs=%d' % (hd.text("name"), size_in_sectors, sector_size) )
	imag = parted.Device( hd.text("name") )
        if hd.has("gpt"):
            disk = parted.freshDisk(imag, "gpt" )
        else:
            disk = parted.freshDisk(imag, "msdos" )

        outf.do_command( 'echo /opt/elbe/' + hd.text("name") + ' >> /opt/elbe/files-to-extract' )

        grub = grubinstaller( outf )

	current_sector = 2048
	for part in hd.node("partitions"):
	    if part.text("size") == "remain" and hd.has("gpt"):
		sz = size_in_sectors - 35 - current_sector;
	    elif part.text("size") == "remain":
		sz = size_in_sectors - current_sector;
	    else:
		sz = size_to_int(part.text("size"))/sector_size

	    g = parted.Geometry (device=imag,start=current_sector,length=sz)
	    ppart = parted.Partition(disk, parted.PARTITION_NORMAL, geometry=g)
	    cons = parted.Constraint(exactGeom=g)
	    disk.addPartition(ppart, cons)

	    if part.has("bootable"):
		ppart.setFlag(_ped.PARTITION_BOOT)

	    if part.has("biosgrub"):
		ppart.setFlag(_ped.PARTITION_BIOS_GRUB)

            partition_number += 1

            if not fslabel.has_key(part.text("label")):
                current_sector += sz
                continue

	    entry = fslabel[part.text("label")]
	    entry.offset = current_sector*sector_size
	    entry.size   = sz * sector_size
	    entry.filename = hd.text("name")
            if hd.has("gpt"):
                entry.number = "gpt%d" % partition_number
            else:
                entry.number = "msdos%d" % partition_number


            if entry.mountpoint == "/":
                grub.set_root_entry( entry )
            elif entry.mountpoint == "/boot":
                grub.set_boot_entry( entry )

            entry.losetup( outf, "loop0" )
	    outf.do_command( 'mkfs.%s %s %s /dev/loop0' % ( entry.fstype, entry.mkfsopt, entry.get_label_opt() ) )

            outf.do_command( 'mount /dev/loop0 %s' % opt.dir )
            outf.do_command( 'cp -a "%s"/* "%s"' % ( os.path.join( '/opt/elbe/filesystems', entry.label ), opt.dir ), allow_fail=True )
            outf.do_command( 'umount /dev/loop0' )
	    outf.do_command( 'losetup -d /dev/loop0' )

	    current_sector += sz

	disk.commit()

        grub.install( opt )


def run_command( argv ):

    oparser = OptionParser( usage="usage: %prog hdimg <xmlfile>")
    oparser.add_option( "--directory", dest="dir",
                        help="mount the loop file here",
                        metavar="FILE" )

    (opt,args) = oparser.parse_args(argv)

    if len(args) != 1:
	print "Wrong number of arguments"
	oparser.print_help()
	sys.exit(20)

    if not opt.dir:
	print "No mount directory specified!"
	oparser.print_help()
	sys.exit(20)

    try:
	xml = etree( args[0] )
    except:
	print "Error reading xml file!"
	sys.exit(20)

    tgt = xml.node("target")

    if not tgt.has("images"):
	print "no images defined"
	sys.exit(20)

    if not tgt.has("fstab"):
	print "no fstab defined"
	sys.exit(20)

    outf = asccidoclog()
    outf.h2( "Formatting Disks" )

    # Build a dictonary of mount points
    fslabel = {}
    for fs in tgt.node("fstab"):
	if fs.tag != "bylabel":
	    continue

	fslabel[fs.text("label")] = fstabentry(fs)

    # Build a sorted list of mountpoints
    fslist = fslabel.values()
    fslist.sort( key = lambda x: x.mountdepth() )

    # now move all mountpoints into own directories
    # begin from deepest mountpoints

    outf.do_command( 'mkdir -p /opt/elbe/filesystems' )

    for l in reversed(fslist):
        outf.do_command( 'mkdir -p "%s"' % os.path.join( '/opt/elbe/filesystems', l.label ) )
        outf.do_command( 'mkdir -p "%s"' % '/target' + l.mountpoint )
        if len(os.listdir( '/target' + l.mountpoint )) > 0:
            outf.do_command( 'mv "%s"/* "%s"' % ( '/target' + l.mountpoint, os.path.join( '/opt/elbe/filesystems', l.label ) ) )

    try:
	# Now iterate over all images and create filesystems and partitions
	for i in tgt.node("images"):
	    if i.tag == "hd":
		do_image_hd( outf, i, fslabel, opt )

	    if i.tag == "mtd":
		mkfs_mtd( outf, i, fslabel )
    finally:
	# Put back the filesystems into /target
	# most shallow fs first...
	for i in fslist:
            if len(os.listdir(os.path.join( '/opt/elbe/filesystems', i.label ))) > 0:
                outf.do_command( 'mv "%s"/* "%s"' % ( os.path.join( '/opt/elbe/filesystems', i.label ), '/target' + i.mountpoint ) )

    # Files are now moved back. ubinize needs files in place, so we run it now.
    for i in tgt.node("images"):
	if i.tag == "mtd":
	    build_image_mtd( outf, i, fslabel )


if __name__ == "__main__":
    run_command( sys.argv[1:] )
    