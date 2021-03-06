import copy
import pytest
import requests_mock

from netboxapi import NetboxMapper, NetboxAPI
from netboxapi.mapper import NetboxPassiveMapper
from netboxapi.exceptions import (
    ForbiddenAsChildError, ForbiddenAsPassiveMapperError
)


class TestNetboxMapper():
    url = "http://localhost/api"
    api = NetboxAPI(url)
    test_app_name = "test_app_name"
    test_model = "test_model"

    @pytest.fixture()
    def mapper(self):
        return self.get_mapper()

    def get_mapper(self):
        return NetboxMapper(self.api, self.test_app_name, self.test_model)

    def test_get(self, mapper):
        url = self.get_mapper_url(mapper)
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{"id": 1, "name": "test"}]
        }
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            child_mapper = next(mapper.get())

        for key, val in expected_attr["results"][0].items():
            assert getattr(child_mapper, key) == val

    def test_get_submodel(self, mapper):
        url = self.get_mapper_url(mapper)
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{"id": 1, "name": "first_model"}]
        }

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", url,
                json={
                    "count": 1, "next": None, "previous": None,
                    "results": [{"id": 1}]
                }
            )
            parent_mapper = next(mapper.get())
            m.register_uri(
                "get", url + "{}/{}/".format(parent_mapper.id, "submodel"),
                json=expected_attr
            )
            submodel_mapper = next(parent_mapper.get("submodel"))

        for key, val in expected_attr["results"][0].items():
            assert getattr(submodel_mapper, key) == val

    def test_get_id(self, mapper):
        url = self.get_mapper_url(mapper) + "1/"
        expected_attr = {"id": 1, "name": "test"}
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            obj = next(mapper.get(1))

        assert obj.name == "test"
        assert obj.id == 1

    def test_get_update_obj(self, mapper):
        url = self.get_mapper_url(mapper) + "1/"
        expected_attr = {"id": 1, "name": "test"}
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            obj = next(mapper.get(1))
            obj_clone = next(obj.get())
            obj_clone = next(obj_clone.get())

        assert obj.name == obj_clone.name
        assert obj.id == obj_clone.id

    def test_get_query(self, mapper):
        url = self.get_mapper_url(mapper) + "?name=test"
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{"id": 1, "name": "test"}]
        }
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            next(mapper.get(name="test"))

    def test_get_submodel_without_id(self, mapper):
        url = self.get_mapper_url(mapper)
        expected_attr = [
            {"vrf": None, "name": "test"},
            {"vrf": 1, "name": "test2"}
        ]
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            next(mapper.get())

    def test_get_pagination(self, mapper):
        url = self.get_mapper_url(mapper)
        next_url = url + "?limit=50&offset=50"
        nb_obj = 75
        results = [
            {"id": i, "name": "test{}".format(i)} for i in range(nb_obj)
        ]

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", url, json={
                    "count": nb_obj, "next": next_url,
                    "previous": None, "results": results[:50]
                }
            )
            m.register_uri(
                "get", next_url, json={
                    "count": nb_obj,
                    "previous": None, "results": results[50:]
                }
            )
            received_list = tuple(mapper.get(limit=50))

        assert len(results) == len(received_list)
        for expected, received in zip(results, received_list):
            assert expected["id"] == received.id
            assert expected["name"] == received.name

    def test_get_submodel_with_choice(self, mapper):
        """
        Choices are enum handled by netbox. Try to get a model with it.
        """
        url = self.get_mapper_url(mapper)
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{
                "id": 1, "name": "test", "choice": {
                    "value": 1, "label": "Some choice"
                }
            }]
        }
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            next(mapper.get())

    def test_cache_foreign_key(self, mapper):
        attr = {
            "id": 1, "name": "test",
            "vrf": {
                "id": 1, "name": "vrf_test",
                "url": mapper.netbox_api.build_model_url("ipam", "vrfs") + "1/"
            }
        }
        child_mapper = self._get_child_mapper_variable_attr(mapper, attr)

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", attr["vrf"]["url"], json={
                    "id": 1, "name": "vrf_test"
                }
            )
            vrf = child_mapper.vrf

        # request mocker is down, so any new request will fail
        assert vrf == child_mapper.vrf

    def test_multiple_get_foreign_key(self, mapper):
        """
        Test multiple get on the same object to control foreign keys behavior

        As foreign keys are properties, a unique class is done to any object
        based on its route. But if multiple successiveget are done on the same
        object, the class does not change and its properties should be
        overriden.
        """
        attr = {
            "id": 1, "name": "test",
            "vrf": {
                "id": 1, "name": "vrf_test",
                "url": mapper.netbox_api.build_model_url("ipam", "vrfs") + "1/"
            }
        }
        child_mapper = self._get_child_mapper_variable_attr(mapper, attr)

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", attr["vrf"]["url"], json={
                    "id": 1, "name": "vrf_test"
                }
            )
            assert child_mapper.vrf.id == 1

        attr["vrf"] = {
            "id": 2,
            "url": mapper.netbox_api.build_model_url("ipam", "vrfs") + "2/"
        }
        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", self.get_mapper_url(child_mapper) + "1/",
                json=attr
            )
            m.register_uri(
                "get", attr["vrf"]["url"], json={
                    "id": 2, "name": "vrf_test2"
                }
            )
            child_mapper = next(child_mapper.get())
            assert child_mapper.vrf.id == 2

    def _get_child_mapper_variable_attr(self, mapper, expected_attr):
        """
        Get child mapper with expected_attr as parameter
        """
        url = self.get_mapper_url(mapper)
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            child_mapper = next(mapper.get())

        return child_mapper

    def test_post(self, mapper):
        url = self.get_mapper_url(mapper)

        with requests_mock.Mocker() as m:
            received_req = m.register_uri(
                "post", url, json=self.update_or_create_resource_json_callback
            )
            m.register_uri(
                "get", url + "1/",
                json={
                    "count": 1, "next": None, "previous": None,
                    "results": [{"id": 1, "name": "testname"}]
                }
            )
            child_mapper = mapper.post(name="testname")

        assert child_mapper.id == 1
        assert child_mapper.name == "testname"

    def test_post_with_failing_get(self, mapper):
        url = self.get_mapper_url(mapper)

        with requests_mock.Mocker() as m:
            m.register_uri(
                "post", url, json=self.update_or_create_resource_json_callback
            )
            m.register_uri(
                "get", url + "1/",
                text="Not Found", status_code=404
            )
            child_mapper = mapper.post(name="testname")

        assert isinstance(child_mapper, NetboxPassiveMapper)
        assert child_mapper.id == 1
        assert child_mapper.name == "testname"

        for m in ("get", "put", "post", "delete"):
            with pytest.raises(ForbiddenAsPassiveMapperError):
                getattr(child_mapper, m)()

    def update_or_create_resource_json_callback(self, request, context):
        json = request.json()
        json["id"] = 1
        assert "created" not in json
        assert "last_updated" not in json
        return json

    def test_post_foreign_key(self, mapper):
        url = self.get_mapper_url(mapper)

        fk_mapper = NetboxMapper(mapper.netbox_api, "foo", "bar")
        fk_mapper.id = 2

        with requests_mock.Mocker() as m:
            received_req = m.register_uri(
                "post", url, json={
                    "id": 1, "name": "testname", "fk": {"id": 2}
                }
            )
            m.register_uri(
                "get", url + "1/",
                json={
                    "count": 1, "next": None, "previous": None,
                    "results": [{
                        "id": 1, "name": "testname", "fk": {
                            "id": 2,
                            "url": self.get_mapper_url(fk_mapper) + "2/"
                        }
                    }]
                }
            )
            mapper.post(name="testname", fk=fk_mapper)

        assert received_req.last_request.json()["fk"] == 2

    def test_post_foreign_key_broken_mapper(self, mapper):
        url = self.get_mapper_url(mapper)

        fk_mapper = NetboxMapper(mapper.netbox_api, "foo", "bar")

        with requests_mock.Mocker() as m:
            m.register_uri(
                "post", url, json={
                    "id": 1, "name": "testname", "fk": {"id": 2}
                }
            )
            with pytest.raises(ValueError):
                mapper.post(name="testname", fk=fk_mapper)

    def test_put(self, mapper):
        child_mapper = self.get_child_mapper(mapper)
        url = self.get_mapper_url(child_mapper) + "{}/".format(child_mapper.id)
        with requests_mock.Mocker() as m:
            received_req = m.register_uri(
                "put", url, json=self.update_or_create_resource_json_callback
            )
            child_mapper.name = "another testname"
            child_mapper.put()

        req_json = received_req.last_request.json()
        assert req_json["name"] == child_mapper.name

    def get_child_mapper(self, mapper):
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{"id": 1, "name": "test"}]
        }
        return self._get_child_mapper_variable_attr(mapper, expected_attr)

    def test_put_with_foreign_key(self, mapper):
        """
        Test that objects that are foreign keys are put by their ID
        """
        child_mapper = self.get_child_mapper_foreign_key(mapper)
        vrf_mapper = NetboxMapper(self.api, "ipam", "vrfs")

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", self.get_mapper_url(vrf_mapper) + "1/",
                json={
                    "count": 1, "next": None, "previous": None,
                    "results": [{"id": 1, "name": "test_vrf"}]
                }
            )
            child_mapper_url = (
                self.get_mapper_url(child_mapper) +
                "{}/".format(child_mapper.id)
            )
            received_req = m.register_uri(
                "put", child_mapper_url,
                json=self.update_or_create_resource_json_callback
            )

            child_mapper.put()

        req_json = received_req.last_request.json()
        assert isinstance(req_json["vrf"], int)

    def test_put_with_null_foreign_key(self, mapper):
        """
        Test PUT with an object previously having a null foreign key
        """
        expected_attr = {
            "id": 1, "name": "test", "vrf": None,
        }
        child_mapper = self._get_child_mapper_variable_attr(
            mapper, expected_attr
        )

        vrf_mapper = NetboxMapper(self.api, "ipam", "vrfs")
        child_vrf_mapper = self._get_child_mapper_variable_attr(
            vrf_mapper, {
                "count": 1, "next": None, "previous": None,
                "results": [{"id": 1, "name": "test_vrf"}]
            }
        )

        with requests_mock.Mocker() as m:
            child_mapper_url = (
                self.get_mapper_url(child_mapper) +
                "{}/".format(child_mapper.id)
            )
            m.register_uri(
                "put", child_mapper_url,
                json=self.update_or_create_resource_json_callback
            )
            child_mapper.vrf = child_vrf_mapper
            req_json = child_mapper.put()

        assert req_json["vrf"] == child_vrf_mapper.id

    def test_put_with_int_foreign_key(self, mapper):
        """
        Test PUT with an object having an id as foreign key, and not a mapper
        """
        child_mapper = self.get_child_mapper_foreign_key(mapper)
        child_mapper.vrf = 2

        with requests_mock.Mocker() as m:
            child_mapper_url = (
                self.get_mapper_url(child_mapper) +
                "{}/".format(child_mapper.id)
            )
            received_req = m.register_uri(
                "put", child_mapper_url,
                json=self.update_or_create_resource_json_callback
            )

            child_mapper.put()

        req_json = received_req.last_request.json()
        assert req_json["vrf"] == 2

    def get_child_mapper_foreign_key(self, mapper):
        expected_attr = {
            "id": 1, "name": "test",
            "vrf": {
                "id": 1, "name": "vrf_test",
                "url": "{}/{}/".format(
                    mapper.netbox_api.build_model_url("ipam", "vrfs"), 1
                ),
            }, "choice": {"value": 1, "label": "Choice"},
            "created": "1970-01-01", "last_updated": "1970-01-01T00:00:00Z",
        }
        return self._get_child_mapper_variable_attr(mapper, expected_attr)

    def test_put_choice(self, mapper):
        """
        Choices are enum handled by netbox. Try to get a model with it.
        """
        child_mapper = self.get_child_mapper_with_choice(mapper)
        url = self.get_mapper_url(child_mapper) + "{}/".format(child_mapper.id)
        with requests_mock.Mocker() as m:
            received_req = m.register_uri(
                "put", url, json=self.update_or_create_resource_json_callback
            )
            child_mapper.put()

        req_json = received_req.last_request.json()
        assert req_json["choice"] == child_mapper.choice["value"]

    def get_child_mapper_with_choice(self, mapper):
        expected_attr = {
            "id": 1, "name": "test",
            "choice": {"value": 1, "label": "Choice"}
        }
        return self._get_child_mapper_variable_attr(mapper, expected_attr)

    def test_delete(self, mapper):
        url = self.get_mapper_url(mapper)
        with requests_mock.Mocker() as m:
            m.register_uri("delete", url + "1/")
            req = mapper.delete(1)

        assert req.status_code == 200

    def test_delete_without_id(self, mapper):
        with pytest.raises(ValueError):
            mapper.delete()

    def test_delete_from_child(self, mapper):
        url = self.get_mapper_url(mapper) + "1/"

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", url, json={"id": 1}
            )
            obj_mapper = next(mapper.get(1))

        with requests_mock.Mocker() as m:
            m.register_uri("delete", url)
            response = obj_mapper.delete()

        assert response.status_code == 200

    def test_delete_other_id_from_child(self, mapper):
        url = self.get_mapper_url(mapper) + "1/"

        with requests_mock.Mocker() as m:
            m.register_uri(
                "get", url, json={"id": 1}
            )
            obj_mapper = next(mapper.get(1))

        with pytest.raises(ForbiddenAsChildError):
            obj_mapper.delete(1)

    def test_eq_equals(self, mapper):
        assert mapper == self.get_mapper()

    def test_eq_not_equals(self, mapper):
        assert mapper != NetboxMapper(self.api, "an_app", "a_model")

    def test_eq_equals_child_mapper(self, mapper):
        expected_attr = {
            "count": 1, "next": None, "previous": None,
            "results": [{
                "id": 1, "name": "test", "created": "1970-01-01",
                "last_updated": "1970-01-01T00:00:00Z"
            }]
        }
        url = self.get_mapper_url(mapper)
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            child_mapper = next(mapper.get())

        expected_attr["results"][0]["created"] = "1971-01-01"
        expected_attr["results"][0]["last_updated"] = "1971-01-01T00:00:00Z"
        with requests_mock.Mocker() as m:
            m.register_uri("get", url, json=expected_attr)
            copy_child_mapper = next(mapper.get())

        assert child_mapper == copy_child_mapper
        copy_child_mapper.name = "else"
        assert child_mapper != copy_child_mapper

    def get_mapper_url(self, mapper):
        return mapper.netbox_api.build_model_url(
            mapper.__app_name__, mapper.__model__
        )
