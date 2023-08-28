from setuptools import setup, find_packages

setup(name='k8sDeploy',
      version='0.1',
      packages=find_packages(),
      install_requires=[
          'boto3',
          'pyyaml',
      ],
      scripts=['k8sdeploy']

      )
