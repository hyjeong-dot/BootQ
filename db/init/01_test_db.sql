-- 테스트 DB (docs/rules/07_TEST.md 2장). postgres 이미지가 볼륨을 처음 만들 때 한 번만 실행한다.
-- 개발 DB(POSTGRES_DB)와 같은 계정이 소유한다. 마이그레이션은 테스트가 시작할 때 적용한다.
SELECT format('CREATE DATABASE bootq_test OWNER %I', current_user)
\gexec
