import boto3
from botocore.exceptions import ClientError
import os, yaml
import jinja2
import json
import tempfile
import base64
from subprocess import run
from six import b

class KubernetesDeploy():
    def __init__(self,var_filename,stack):
        self.stack=stack
        self.account=""
        self.vars=self.__deploy_data__(var_filename)
    
    def __deploy_data__(self,filename):
        if self.checkAWSToken():
            var_data=self.read_variable_file(filename)
            secret_cm=self.generate_secret_configmap_data(var_data)
            data = secret_cm | var_data
            data = self.load_defaults('default_vars.yml',data) | data 
            #data = self.read_variable_file('k8s_vars/default_vars.yml') | data
            data=self.get_cert_arn(data)
            data=self.get_tag_data(data)
            d=data.pop("target_app_secrets_ref",None)
            d=data.pop("target_app_env",None)
            return data
            
    def load_defaults(self,filename,data, path="./default_vars"):
        templateLoader = jinja2.FileSystemLoader(searchpath=path)
        template_env=jinja2.Environment(loader=templateLoader, autoescape=True)
        template=template_env.get_template(filename)
        return yaml.safe_load(template.render(**data))

    def get_tag_data(self, var_data):
        lookup={"dev":"Development","prod":"Production","stage":"Stage","sand":"Development"}
        var_data['stack']=self.stack
        var_data['environment']=lookup[self.stack]
        return var_data

    def get_secret(self,secret_name,region_name="us-east-1"):
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name,
        )

        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_name
            )
        except ClientError as e:
            print(e.response['Error']['Code'])
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print("The requested secret " + secret_name + " was not found")
            elif e.response['Error']['Code'] == 'InvalidRequestException':
                print("The request was invalid due to:", e)
            elif e.response['Error']['Code'] == 'InvalidParameterException':
                print("The request had invalid params:", e)
            elif e.response['Error']['Code'] == 'DecryptionFailure':
                print("The requested secret can't be decrypted using the provided KMS key:", e)
            elif e.response['Error']['Code'] == 'InternalServiceError':
                print("An error occurred on service side:", e)
        else:
            # Secrets Manager decrypts the secret value using the associated KMS CMK
            # Depending on whether the secret was a string or binary, only one of these fields will be populated
            if 'SecretString' in get_secret_value_response:
                text_secret_data = get_secret_value_response['SecretString']
                return base64.b64encode(b(text_secret_data)).decode('utf-8') 
            else:
                print("binary data", get_secret_value_response['SecretBinary'])
                binary_secret_data = get_secret_value_response['SecretBinary']
                return binary_secret_data

    def checkAWSToken(self):
        """
        Check if AWS Token has expired
        """
        status=True
        sts = boto3.client('sts')
        try:
            account=sts.get_caller_identity()['Account']
            self.account=account
        except ClientError as e:
            if e.response['Error']['Code'] == 'ExpiredToken':
                print("The AWS Token has expired. Please login to the AWS CLI and try again.")
                status=False
        return status

    def get_cert_arn(self,var_data):
        arn= None
        if 'aws_load_balancer_ssl_cert' in var_data:
            arn= var_data['aws_load_balancer_ssl_cert']
        else:
            acm=boto3.client('acm')
            all_certs=acm.list_certificates()
            for cert in all_certs['CertificateSummaryList']:
                if cert['DomainName'].endswith(f"{self.stack}.apis.huit.harvard.edu"):
                    arn= cert['CertificateArn']
        if not arn:
            raise Exception("Unable to find ARN for ALB Certificate")

        var_data['aws_load_balancer_ssl_cert']=arn
        return var_data

    def read_variable_file(self,filename):
        with open(filename, 'r') as f1:
            return yaml.safe_load(f1.read())

    def generate_secret_configmap_data(self,var_data):
        data={"secret":{},"configmap":{}} 
        if 'target_app_secrets_ref' in var_data:
            for itm in var_data['target_app_secrets_ref']:
                for i in itm:
                    secret_name="{0}/{1}".format(self.stack,itm[i])
                    value=self.get_secret(secret_name)
                    data["secret"][i]="".join(value.split())
        if 'target_app_env' in var_data:
            for itm in var_data['target_app_env']:
                data["configmap"][itm['name']]="".join(itm['value'].split())
        return data

    def load_template(self,template_name,data, custom_path=None):
        templateLoader = jinja2.FileSystemLoader(searchpath="./templates")
        template_env=jinja2.Environment(loader=templateLoader, autoescape=True)
        template=template_env.get_template(f"{template_name}.j2")
        return template.render(**data)

    def load_deploy(self,template,action):
        try:
            rendered=self.load_template(template,self.vars)
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
                temp_file.write(rendered)
            run(['kubectl', action ,'-f',temp_file.name ])
        except Exception as e:
            print (e)
        finally:
            # Ensure tempfile is closed and removed
            temp_file.close()
            os.unlink(temp_file.name)

    def deploy_objects(self,action="apply",delete_namespace=False):
        if self.checkAWSToken():
            # Deploy k8s objects
            if action != "delete":
                self.load_deploy("namespace",action)
            if self.vars['secret']:
                self.load_deploy("secret",action)
            if self.vars['configmap']:
                self.load_deploy("configmap",action)
            self.load_deploy("deployment",action)
            self.load_deploy("service",action)
            if self.vars['create_ingress']:
                self.load_deploy("ingress",action)
            if action=="delete" and delete_namespace:
                self.load_deploy("namespace",action)