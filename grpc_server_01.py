import os
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import hello01_pb2
import hello01_pb2_grpc


class HelloService01(hello01_pb2_grpc.HelloService01Servicer):
    def SayHello(self, request, context):
        env_name = os.getenv("RUN_ENV", "unknown")
        return hello01_pb2.HelloReply(
            message=f"hello {env_name} from gRPC server 01, {request.name}!"
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    hello01_pb2_grpc.add_HelloService01Servicer_to_server(HelloService01(), server)

    service_names = (
        hello01_pb2.DESCRIPTOR.services_by_name["HelloService01"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    server.add_insecure_port("[::]:50051")
    print("gRPC server 01 listening on port 50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
