import aioboto3


async def get_credentials(session: aioboto3.Session, role_arn: str,
                          username: str, id_token: str):
    """Fetch temporary AWS credentials from STS."""
    async with session.client('sts') as client:
        return await client.assume_role_with_web_identity(
            RoleArn=role_arn,
            RoleSessionName=f'{username}-imbi',
            WebIdentityToken=id_token)


async def get_parameters_by_path(session: aioboto3.Session, path: str,
                                 access_key_id: str, secret_access_key: str,
                                 session_token: str) -> list:
    """Fetch all SSM parameters under the specified path."""
    async with session.client('ssm',
                              aws_access_key_id=access_key_id,
                              aws_secret_access_key=secret_access_key,
                              aws_session_token=session_token) as client:

        params = []
        paginator = client.get_paginator('get_parameters_by_path')
        async for page in paginator.paginate(Path=path,
                                             Recursive=True,
                                             WithDecryption=True,
                                             MaxResults=10):
            params.extend(page['Parameters'])
        return params


async def put_parameter(session: aioboto3.Session,
                        access_key_id: str,
                        secret_access_key: str,
                        session_token: str,
                        path: str,
                        param_type: str,
                        value: str,
                        overwrite: bool = False):
    async with session.client('ssm',
                              aws_access_key_id=access_key_id,
                              aws_secret_access_key=secret_access_key,
                              aws_session_token=session_token) as client:
        await client.put_parameter(Name=path,
                                   Value=value,
                                   Type=param_type,
                                   Overwrite=overwrite)


async def delete_parameter(session: aioboto3.Session, access_key_id: str,
                           secret_access_key: str, session_token: str,
                           path: str):
    async with session.client('ssm',
                              aws_access_key_id=access_key_id,
                              aws_secret_access_key=secret_access_key,
                              aws_session_token=session_token) as client:
        await client.delete_parameter(Name=path)
