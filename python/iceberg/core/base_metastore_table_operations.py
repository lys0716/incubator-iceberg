# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import uuid

from iceberg.core.hadoop import (get_fs,
                                 HadoopInputFile,
                                 HadoopOutputFile)
from retrying import retry

from .table_metadata_parser import TableMetadataParser
from .table_operations import TableOperations

_logger = logging.getLogger(__name__)


class BaseMetastoreTableOperations(TableOperations):

    TABLE_TYPE_PROP = "table_type"
    ICEBERG_TABLE_TYPE_VALUE = "iceberg"
    METADATA_LOCATION_PROP = "metadata_location"
    PREVIOUS_METADATA_LOCATION_PROP = "previous_metadata_location"

    METADATA_FOLDER_NAME = "metadata"
    DATA_FOLDER_NAME = "data"
    HIVE_LOCATION_FOLDER_NAME = "empty"

    def __init__(self, conf):
        self.conf = conf

        self.current_metadata = None
        self.current_metadata_location = None
        self.base_location = None
        self.version = -1

    def current(self):
        return self.current_metadata

    def hive_table_location(self):
        return "{base_location}/{hive}".format(base_location=self.base_location,
                                               hive=BaseMetastoreTableOperations.HIVE_LOCATION_FOLDER_NAME)

    def data_location(self):
        return "{base_location}/{data}".format(base_location=self.base_location,
                                               data=BaseMetastoreTableOperations.DATA_FOLDER_NAME)

    def write_new_metadata(self, metadata, version):
        if self.base_location is None:
            self.base_location = metadata.location

        new_filename = BaseMetastoreTableOperations.new_table_metadata_filename(self.base_location,
                                                                                version)
        new_metadata_location = HadoopOutputFile.from_path(new_filename, self.conf)

        TableMetadataParser.write(metadata, new_metadata_location)
        return new_filename

    def refresh_from_metadata_location(self, new_location, num_retries=20):
        if not self.current_metadata_location == new_location:
            _logger.info("Refreshing table metadata from new version: %s" % new_location)

        self.retryable_refresh(new_location)

    def new_input_file(self, path):
        return HadoopInputFile.from_location(path, self.conf)

    def new_metadata_file(self, filename):
        return HadoopOutputFile.from_path(BaseMetastoreTableOperations.new_metadata_location(self.base_location,
                                                                                             filename),
                                          self.conf)

    def delete_file(self, path):
        get_fs(path, self.conf).delete(path, False)

    @retry(wait_incrementing_start=100, wait_exponential_multiplier=4,
           wait_exponential_max=5000, stop_max_delay=600000, stop_max_attempt_number=2)
    def retryable_refresh(self, location):
        self.current_metadata = TableMetadataParser.read(self, HadoopInputFile.from_location(location, self.conf))
        self.current_metadata_location = location
        self.base_location = self.current_metadata.location
        self.version = BaseMetastoreTableOperations.parse_version(location)

    @staticmethod
    def parse_version(metadata_location):
        version_start = metadata_location.rfind("/") + 1
        version_end = version_start + metadata_location[version_start:].find("-")
        return int(metadata_location[version_start:version_end])

    @staticmethod
    def new_metadata_location(base_location, filename):
        return "{}/{}/{}".format(base_location, BaseMetastoreTableOperations.METADATA_FOLDER_NAME, filename)

    @staticmethod
    def new_table_metadata_filename(base_location, new_version):
        return "{}/{}/{}-{}.metadata.json".format(base_location,
                                                  BaseMetastoreTableOperations.METADATA_FOLDER_NAME,
                                                  '%05d' % new_version,
                                                  uuid.uuid4())
