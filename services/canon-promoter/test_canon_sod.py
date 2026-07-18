"""Compatibility entry point for the canonical canon SoD suite."""
import os,runpy,sys
ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),"../.."))
sys.path.insert(0,os.path.join(ROOT,"libs"))
runpy.run_path(os.path.join(ROOT,"tests","test_canon_sod.py"),run_name="__main__")
