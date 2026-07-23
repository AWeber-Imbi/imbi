# 5. File Upload Storage Architecture

Date: 2026-02-06

## Status

Accepted

## Context

Imbi v2 needs a general-purpose file upload system. All `Node`-based
entities (Organization, Team, Environment, ProjectType, Project) have
an `icon` field (`pydantic.HttpUrl | str | None`), but there is
currently no way to upload files. The platform needs to store icons,
avatars, documents, and other assets associated with entities.

### Requirements

1. **File Types**: Support images (JPEG, PNG, GIF, WebP, SVG) and
   documents (PDF) with magic-byte validation
2. **Thumbnails**: Automatic thumbnail generation for raster images
3. **Serving**: Efficient file serving without proxying through the API
4. **Security**: Content type validation, size limits, permission-based
   access control
5. **Development**: Local development without cloud credentials
6. **Scalability**: Support for large deployments with many assets

## Decision

### 1. Storage Backend

**S3-Compatible Object Storage**

We will use S3-compatible storage with the `aioboto3` library for
native async/await operations.

**Rationale**:
- **Industry standard**: Well-understood API, extensive tooling
- **Scalable**: Handles files from bytes to terabytes
- **Cost-effective**: Pay-per-use pricing in production
- **Presigned URLs**: Efficient file serving without proxying
- **Async support**: `aioboto3` provides native async S3 operations

**Trade-offs**:
- Additional infrastructure dependency
- Requires AWS credentials in production
- Acceptable: S3 is ubiquitous and well-supported

**Alternatives Considered**:
- **Neo4j base64**: Rejected. Bloats graph database, not designed for
  blob storage, degrades query performance
- **ClickHouse**: Rejected. Works for small files but not designed as a
  blob store, inefficient for binary data retrieval
- **Local filesystem**: Rejected. Does not scale across multiple
  instances, not portable across deployments

### 2. Development Environment

**LocalStack (not MinIO)**

We will use LocalStack for local S3 emulation in development.

**Rationale**:
- **Full AWS API emulation**: Not just S3, covers additional AWS
  services if needed in the future
- **Production parity**: Same S3 API as real AWS
- **Single container**: One service emulates all AWS APIs
- **Active maintenance**: Well-supported, frequent releases
- **Docker-friendly**: Works in Docker Compose alongside existing
  services

**Trade-offs**:
- Heavier container than MinIO
- Acceptable: Development convenience outweighs container size

**Alternative Considered**:
- **MinIO**: S3-compatible but only covers S3. LocalStack provides
  broader AWS API coverage for potential future needs

### 3. Metadata Storage

**Neo4j for Upload Metadata**

Upload metadata (filename, content type, size, S3 key) is stored as
Neo4j nodes, consistent with all other entities in Imbi.

**Rationale**:
- **Consistency**: All entity metadata lives in Neo4j
- **Relationships**: Can link uploads to entities via graph edges
- **Querying**: Standard Cypher queries for listing and filtering
- **Indexing**: UUID constraint for fast lookups

### 4. File Serving

**Presigned URL Redirects (307)**

The API returns HTTP 307 redirects to presigned S3 URLs rather than
proxying file content.

**Rationale**:
- **Performance**: No API server bandwidth consumed for file serving
- **Scalability**: S3 handles download traffic directly
- **Simplicity**: No streaming or chunked transfer logic needed
- **Cacheability**: Presigned URLs can be cached by clients

**Trade-offs**:
- Requires S3 endpoint accessible to clients
- Presigned URLs have expiration (mitigated with reasonable TTL)
- Acceptable: Standard pattern for S3-backed file APIs

### 5. Image Processing

**Pillow for Thumbnails, filetype for Validation**

We will use Pillow for generating WEBP thumbnails and `filetype` for
magic-byte content type validation.

**Rationale**:
- **Pillow**: Mature, well-tested image processing library
- **filetype**: Pure Python magic-byte detection, no libmagic dependency
- **WEBP thumbnails**: Modern format with good compression and quality
- **Executor-based**: Pillow runs in thread executor to avoid blocking

**Thumbnail Strategy**:
- Max 256x256 pixels, maintaining aspect ratio
- WEBP format at 85% quality
- Only for raster images (not SVG)
- Stored alongside originals in S3

## Consequences

### Positive

1. **Scalability**: S3 handles any volume of file storage
2. **Performance**: Presigned URLs avoid proxying through API
3. **Security**: Magic-byte validation prevents content type spoofing
4. **Developer Experience**: LocalStack provides local S3 with no
   cloud credentials needed
5. **Consistency**: Upload metadata in Neo4j alongside other entities
6. **Thumbnails**: Automatic thumbnail generation for image previews
7. **Async**: All S3 operations are async via aioboto3

### Negative

1. **Infrastructure**: New dependency on S3/LocalStack
2. **Credentials**: AWS credentials required in production
3. **Complexity**: Presigned URL expiration must be managed
4. **Dependencies**: Three new Python packages (aioboto3, filetype,
   Pillow)

### Mitigation Strategies

1. **Infrastructure**: LocalStack in dev, S3 in production is standard
2. **Credentials**: Use IAM roles in production, env vars in dev
3. **Expiration**: Generous presigned URL TTL (1 hour default)
4. **Dependencies**: All are well-maintained, widely used packages

## References

- [aioboto3 Documentation](https://aioboto3.readthedocs.io/)
- [LocalStack](https://localstack.cloud/)
- [Pillow Documentation](https://pillow.readthedocs.io/)
- [filetype](https://github.com/h2non/filetype.py)
- [S3 Presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
