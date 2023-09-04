#!/usr/bin/env python

import os
import argparse
from k8sdeploy.k8sdeploy import KubernetesDeploy

class UserNamespace(object):
    """ Arg Parser class """
    pass

def main():
    user_namespace = UserNamespace()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-s","--stack", type=str,default="dev",
                        help="stack(default='dev')")
    parser.add_argument("-a","--action", type=str,default="apply",
                        help="Action verb: create, delete, apply (default='apply')")
    parser.parse_known_args(namespace=user_namespace)
    parser1 = argparse.ArgumentParser(description="Create K8s artifacts within cluster.", 
    parents=[parser])
    parser1.add_argument("-f","--filename", type=str, 
                        default="{0}/k8s_vars/{1}_k8s_vars.yml".format(os.getcwd(),user_namespace.stack) ,
                        help="""Specific filename to pass in k8s vars yaml file. 
                                Default: {current directory}/k8s_vars/{stack}_k8s_vars.yml
                                """)
    args=parser1.parse_args()
    
    deploy=KubernetesDeploy(args.filename,args.stack)
    deploy.deploy_objects(action=args.action)

