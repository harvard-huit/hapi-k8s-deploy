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
    parser.add_argument("-d","--delete-namespace", action='store_true',help="Delete Namespace: only used if action is 'delete'")
    parser.parse_known_args(namespace=user_namespace)
    parser1 = argparse.ArgumentParser(description="Create K8s artifacts within cluster.", 
    parents=[parser])
    parser1.add_argument("-f","--filename", type=str, 
                        default="{0}/k8s_vars/{1}_k8s_vars.yml".format(os.getcwd(),user_namespace.stack) ,
                        help="""Specific filename to pass in k8s vars yaml file. 
                                Default: {current directory}/k8s_vars/{stack}_k8s_vars.yml
                                """)
    parser1.add_argument("-e","--ecr-account", type=str, 
                        default=f"{os.getenv('ECR_ACCOUNT_ID','')}",
                        help="""ECR Account ID. Default: Environment Variable 'ECR_ACCOUNT_ID'""")
    parser1.add_argument("-r","--release-tag", type=str, 
                        default="",
                        help="""Github Release Tag: Default is an empty string resolve to false""")
    args=parser1.parse_args()
    deploy=KubernetesDeploy(args.filename,args.stack,args.ecr_account,args.release_tag)
    deploy.deploy_objects(action=args.action,delete_namespace=args.delete_namespace)