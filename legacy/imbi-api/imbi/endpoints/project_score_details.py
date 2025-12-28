import collections.abc
import decimal
import operator
import typing

import pydantic

from imbi import errors, models
from imbi.endpoints import base

# makes pydantic serialize decimal.Decimal as a float instead of a string
JsonDecimal = typing.Annotated[decimal.Decimal,
                               pydantic.PlainSerializer(
                                   lambda x: float(x),
                                   return_type=float,
                                   when_used='json',
                               )]


class ScoreDetail(pydantic.BaseModel):
    name: str
    fact_type: str
    data_type: str
    value: typing.Union[str, bool, float, int, None]
    score: JsonDecimal
    weight: int


class EnumValue(pydantic.BaseModel):
    value: str
    score: JsonDecimal
    selected: bool


class EnumScoreDetail(ScoreDetail):
    enums: list[EnumValue]


class RangeValue(pydantic.BaseModel):
    value: tuple[float, float]
    score: JsonDecimal
    selected: bool


class RangeScoreDetail(ScoreDetail):
    ranges: list[RangeValue]


FactId = int
FactRow = collections.abc.Mapping[str, typing.Union[int, str, float]]
FactMap = collections.abc.Mapping[FactId, collections.abc.Sequence[FactRow]]


class ProjectScoreDetailHandler(base.AuthenticatedRequestHandler):
    """Implementation of the v1.project_score() stored proc in Python

    The stored procedure is the "source of truth" for the project
    score. This is a facsimile to explain what goes in to the score
    calculation and how changes could affect the score.

    """
    NAME = 'project-score-detail'

    async def get(self, project_id: int) -> None:
        result = await self.postgres_execute(
            'SELECT project_type_id'
            '  FROM v1.projects'
            ' WHERE id = %(project_id)s', {'project_id': project_id})
        if not result:
            raise errors.ItemNotFound()

        facts = await models.project_facts(project_id, self.application)
        enum_details = await self._gather_facts(
            [f.id for f in facts if f.fact_type == 'enum'],
            'SELECT fact_type_id, value, score'
            '  FROM v1.project_fact_type_enums'
            ' WHERE fact_type_id IN %(fact_type_ids)s',
            'score',
            'value',
        )
        range_details = await self._gather_facts(
            [f.id for f in facts if f.fact_type == 'range'],
            'SELECT fact_type_id, score, min_value, max_value'
            '  FROM v1.project_fact_type_ranges'
            ' WHERE fact_type_id IN %(fact_type_ids)s',
            'score',
        )
        scored_facts = sorted((f for f in facts if f.weight),
                              key=operator.attrgetter('weight'),
                              reverse=True)

        # imbi.models sets the process-wide precision to 2 but
        # the database calculation uses decimal(9, 2) so we need
        # to use a matching precision
        with decimal.localcontext() as ctx:
            ctx.prec = 9
            scored_values = self._generate_score_detail(
                scored_facts, enum_details, range_details)
            total_score = sum(value.weight * value.score
                              for value in scored_values)
            total_weight = sum(f.weight for f in scored_facts)
            self.send_response({
                'score': total_score / total_weight,
                'scored_facts': scored_values,
                'unscored_facts': [{
                    'name': f.name,
                    'fact_type': f.fact_type,
                    'data_type': f.data_type,
                    'score': None,
                    'value': f.value,
                    'weight': 0,
                } for f in facts if not f.weight]
            })

    async def _gather_facts(self, fact_ids: collections.abc.Sequence[int],
                            query: str, *sort_params: str) -> FactMap:
        details = collections.defaultdict[int, list[dict]](list)
        if fact_ids:
            result = await self.postgres_execute(
                query, {'fact_type_ids': tuple(fact_ids)})
            for row in result:
                details[row['fact_type_id']].append(row)
        for value in details.values():
            value.sort(key=operator.itemgetter(*sort_params), reverse=True)
        return details

    @staticmethod
    def _generate_score_detail(
        scored_facts: typing.Sequence[models.ProjectFact],
        enum_details,
        range_details,
    ) -> list['ScoreDetail']:
        scored_values = []
        for fact in scored_facts:
            if fact.data_type == 'boolean':
                score = decimal.Decimal(100.0 if fact.value else 0)
            else:
                score = fact.score

            score_detail: ScoreDetail = ScoreDetail(
                name=fact.name,
                fact_type=fact.fact_type,
                data_type=fact.data_type,
                value=fact.value,
                score=score,
                weight=fact.weight,
            )
            if fact.fact_type == 'range':
                ranges = [
                    RangeValue(
                        value=(r['min_value'], r['max_value']),
                        score=r['score'],
                        selected=(r['min_value'] <
                                  (fact.value or 0) <= r['max_value']),
                    ) for r in range_details[fact.id]
                ]
                score_detail = RangeScoreDetail.model_validate(
                    score_detail.model_dump() | {'ranges': ranges})
            elif fact.fact_type == 'enum':
                enums = [
                    EnumValue(value=e['value'],
                              score=e['score'],
                              selected=fact.value == e['value'])
                    for e in enum_details[fact.id]
                ]
                score_detail = EnumScoreDetail.model_validate(
                    score_detail.model_dump() | {'enums': enums})
            scored_values.append(score_detail)

        return scored_values
